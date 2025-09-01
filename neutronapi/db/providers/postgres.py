import json
import datetime
from typing import Optional, Dict, List, Any, Tuple

from .base import BaseProvider


class PostgreSQLProvider(BaseProvider):
    """Async PostgreSQL provider using asyncpg with lazy connection pooling.

    Includes schema operations mirroring the SQLite provider API. Uses
    app label as PostgreSQL schema and table_base_name as the table name.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._pool = None
        self._pool_lock = None
        self._loop = None
        self._conn_kwargs = None
        self._server_settings = None

    async def connect(self):
        import asyncio
        self._pool_lock = asyncio.Lock()
        # base connection kwargs
        self._conn_kwargs = {
            'host': self.config.get('HOST', 'localhost'),
            'port': self.config.get('PORT', 5432),
            'database': self.config.get('NAME', 'temp_db'),
            'user': self.config.get('USER', 'postgres'),
            'password': self.config.get('PASSWORD', ''),
        }
        self._conn_kwargs = {k: v for k, v in self._conn_kwargs.items() if v is not None}

        # Support DATABASES['default']['OPTIONS']
        options = dict(self.config.get('OPTIONS', {}) or {})
        # asyncpg supports server_settings to set GUCs on connect
        if 'server_settings' in options:
            self._server_settings = dict(options['server_settings'])
        elif 'SET' in options:
            # Allow shorthand {'SET': {'statement_timeout': '5s'}}
            self._server_settings = {str(k): str(v) for k, v in options['SET'].items()}
        else:
            self._server_settings = None

        await self._ensure_connectivity()
        await self.create_tables()

    async def _ensure_connectivity(self):
        try:
            import asyncpg
        except ImportError:
            raise ImportError("asyncpg required for PostgreSQL support")
        try:
            conn = await asyncpg.connect(**self._conn_kwargs)
            await conn.close()
        except Exception as e:
            raise ConnectionError(f"Failed to connect to PostgreSQL: {e}") from e

    async def _get_pool(self):
        import asyncio
        import asyncpg
        loop = asyncio.get_running_loop()
        async with self._pool_lock:
            if self._pool is not None and self._loop is not loop:
                await self._close_pool_nolock()
            if self._pool is None:
                create_pool_kwargs = dict(self._conn_kwargs)
                if self._server_settings:
                    create_pool_kwargs['server_settings'] = self._server_settings
                # Use sensible defaults; no project-specific env flags
                self._pool = await asyncpg.create_pool(min_size=1, max_size=10, **create_pool_kwargs)
                self._loop = loop
            return self._pool

    async def _close_pool_nolock(self):
        pool, self._pool = self._pool, None
        old_loop, self._loop = self._loop, None
        if pool is not None:
            try:
                await pool.close()
            except Exception:
                pass

    async def disconnect(self):
        if self._pool_lock is None:
            return
        async with self._pool_lock:
            await self._close_pool_nolock()

    async def execute(self, query: str, params: Tuple = ()) -> Any:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return await conn.execute(query, *params)

    async def fetchone(self, query: str, params: Tuple = ()) -> Optional[Dict[str, Any]]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            return dict(row) if row else None

    async def fetchall(self, query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def create_tables(self):
        import asyncpg
        sql = """
        CREATE TABLE IF NOT EXISTS objects (
            id TEXT PRIMARY KEY,
            key TEXT UNIQUE NOT NULL,
            name TEXT,
            kind TEXT NOT NULL DEFAULT 'file',
            meta JSONB,
            store JSONB,
            connections JSONB,
            folder TEXT,
            parent TEXT,
            sha256 TEXT,
            size INTEGER,
            content_type TEXT,
            latest_revision TEXT,
            vec BYTEA,
            created TIMESTAMP WITH TIME ZONE,
            modified TIMESTAMP WITH TIME ZONE
        )
        """
        connect_kwargs = dict(self._conn_kwargs)
        if self._server_settings:
            connect_kwargs['server_settings'] = self._server_settings
        conn = await asyncpg.connect(**connect_kwargs)
        try:
            await conn.execute(sql)
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_objects_key ON objects(key)",
                "CREATE INDEX IF NOT EXISTS idx_objects_folder ON objects(folder)",
                "CREATE INDEX IF NOT EXISTS idx_objects_parent ON objects(parent)",
                "CREATE INDEX IF NOT EXISTS idx_objects_kind ON objects(kind)",
                "CREATE INDEX IF NOT EXISTS idx_objects_modified ON objects(modified)",
            ]
            for idx in indexes:
                await conn.execute(idx)
        finally:
            await conn.close()

    def serialize(self, data: Any) -> Any:
        if data is None:
            return None
        def default_serializer(o):
            if isinstance(o, datetime.datetime):
                return o.isoformat()
            raise TypeError()
        return json.dumps(data, default=default_serializer)

    def deserialize(self, data: Any) -> Any:
        if data is None:
            return None
        if isinstance(data, (dict, list)):
            return data
        if isinstance(data, str):
            return json.loads(data)
        return data

    def convert_query_param(self, value: Any, field) -> Any:
        """Convert query parameter values for PostgreSQL-specific requirements."""
        # PostgreSQL handles datetime objects natively, no conversion needed
        return value

    # Schema operations
    def _pg_ident(self, name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    def _process_default_value(self, default: Any) -> str:
        value = default() if callable(default) else default
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, datetime.datetime):
            return f"'{value.isoformat()}'"
        if isinstance(value, (dict, list)):
            return f"'{json.dumps(value)}'::jsonb"
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
        return "'" + str(value).replace("'", "''") + "'"

    def get_column_type(self, field) -> str:
        from ..fields import (
            BooleanField,
            VectorField,
            JSONField,
            CharField,
            TextField,
            IntegerField,
            DateTimeField,
            EnumField,
            FloatField,
            BinaryField,
        )
        mapping = {
            CharField: "TEXT",
            TextField: "TEXT",
            IntegerField: "INTEGER",
            BooleanField: "BOOLEAN",
            DateTimeField: "TIMESTAMP WITH TIME ZONE",
            JSONField: "JSONB",
            VectorField: "BYTEA",
            BinaryField: "BYTEA",
            EnumField: "TEXT",
            FloatField: "DOUBLE PRECISION",
        }
        if isinstance(field, CharField) and getattr(field, 'max_length', None):
            return f"VARCHAR({int(field.max_length)})"
        return mapping.get(type(field), "TEXT")

    async def table_exists(self, table_name: str) -> bool:
        if '.' in table_name:
            schema, tbl = table_name.split('.', 1)
            row = await self.fetchone(
                "SELECT 1 FROM information_schema.tables WHERE table_schema=$1 AND table_name=$2",
                (schema, tbl),
            )
        else:
            row = await self.fetchone(
                "SELECT 1 FROM information_schema.tables WHERE table_name=$1",
                (table_name,),
            )
        return row is not None

    async def column_exists(self, app_label: str, table_base_name: str, column_name: str) -> bool:
        row = await self.fetchone(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema=$1 AND table_name=$2 AND column_name=$3
            """,
            (app_label, table_base_name, column_name),
        )
        return row is not None

    async def get_column_info(self, app_label: str, table_base_name: str) -> list:
        rows = await self.fetchall(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema=$1 AND table_name=$2
            ORDER BY ordinal_position
            """,
            (app_label, table_base_name),
        )
        out = []
        for r in rows:
            out.append(
                {
                    "name": r["column_name"] if isinstance(r, dict) else r[0],
                    "type": r["data_type"] if isinstance(r, dict) else r[1],
                    "notnull": (r["is_nullable"] if isinstance(r, dict) else r[2]) == 'NO',
                    "dflt_value": r["column_default"] if isinstance(r, dict) else r[3],
                    "pk": False,
                }
            )
        return out

    async def create_table(self, app_label: str, table_base_name: str, fields: List[Tuple[str, Any]]):
        schema = self._pg_ident(app_label)
        table = self._pg_ident(table_base_name)
        await self.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        if await self.table_exists(f"{app_label}.{table_base_name}"):
            return
        field_defs = []
        primary_keys = []
        for name, field in fields:
            col = self._pg_ident(name)
            coltype = self.get_column_type(field)
            parts = [f"{col} {coltype}"]
            if getattr(field, 'primary_key', False):
                primary_keys.append(col)
                if not getattr(field, 'null', False):
                    parts.append("NOT NULL")
            else:
                if not getattr(field, 'null', False):
                    parts.append("NOT NULL")
                if getattr(field, 'unique', False):
                    parts.append("UNIQUE")
                default = getattr(field, 'default', None)
                if default is not None:
                    default_sql = self._process_default_value(default)
                    if default_sql != "NULL":
                        parts.append(f"DEFAULT {default_sql}")
            field_defs.append(" ".join(parts))
        if primary_keys:
            field_defs.append(f"PRIMARY KEY ({', '.join(primary_keys)})")
        await self.execute(f"CREATE TABLE {schema}.{table} ({', '.join(field_defs)})")

    async def drop_table(self, app_label: str, table_base_name: str):
        await self.execute(f"DROP TABLE IF EXISTS {self._pg_ident(app_label)}.{self._pg_ident(table_base_name)} CASCADE")

    async def add_column(self, app_label: str, table_base_name: str, field_name: str, field: Any):
        coltype = self.get_column_type(field)
        sql = f"ALTER TABLE {self._pg_ident(app_label)}.{self._pg_ident(table_base_name)} ADD COLUMN {self._pg_ident(field_name)} {coltype}"
        default = getattr(field, 'default', None)
        if default is not None:
            sql += f" DEFAULT {self._process_default_value(default)}"
        await self.execute(sql)
        if not getattr(field, 'null', False):
            await self.execute(f"ALTER TABLE {self._pg_ident(app_label)}.{self._pg_ident(table_base_name)} ALTER COLUMN {self._pg_ident(field_name)} SET NOT NULL")
        if getattr(field, 'unique', False):
            await self.execute(f"ALTER TABLE {self._pg_ident(app_label)}.{self._pg_ident(table_base_name)} ADD CONSTRAINT {self._pg_ident(table_base_name + '_' + field_name + '_key')} UNIQUE ({self._pg_ident(field_name)})")

    async def alter_column(self, app_label: str, table_base_name: str, field_name: str, field: Any):
        schema = self._pg_ident(app_label)
        table = self._pg_ident(table_base_name)
        col = self._pg_ident(field_name)
        coltype = self.get_column_type(field)
        await self.execute(f"ALTER TABLE {schema}.{table} ALTER COLUMN {col} TYPE {coltype}")
        if not getattr(field, 'null', False):
            await self.execute(f"ALTER TABLE {schema}.{table} ALTER COLUMN {col} SET NOT NULL")
        else:
            await self.execute(f"ALTER TABLE {schema}.{table} ALTER COLUMN {col} DROP NOT NULL")
        default = getattr(field, 'default', None)
        if default is None:
            await self.execute(f"ALTER TABLE {schema}.{table} ALTER COLUMN {col} DROP DEFAULT")
        else:
            await self.execute(f"ALTER TABLE {schema}.{table} ALTER COLUMN {col} SET DEFAULT {self._process_default_value(default)}")

    async def remove_column(self, app_label: str, table_base_name: str, field_name: str):
        await self.execute(f"ALTER TABLE {self._pg_ident(app_label)}.{self._pg_ident(table_base_name)} DROP COLUMN IF EXISTS {self._pg_ident(field_name)} CASCADE")

    async def rename_table(self, old_app_label: str, old_base: str, new_app_label: str, new_base: str):
        old_schema = self._pg_ident(old_app_label)
        new_schema = self._pg_ident(new_app_label)
        old_table = self._pg_ident(old_base)
        new_table = self._pg_ident(new_base)
        await self.execute(f"CREATE SCHEMA IF NOT EXISTS {new_schema}")
        moved = False
        if old_app_label != new_app_label:
            await self.execute(f"ALTER TABLE {old_schema}.{old_table} SET SCHEMA {new_schema}")
            moved = True
        if old_base != new_base:
            # After a schema move, the current table name under new_schema is still old_table
            current_table = old_table
            await self.execute(f"ALTER TABLE {new_schema}.{current_table} RENAME TO {new_table}")

    async def rename_column(self, app_label: str, table_base_name: str, old_name: str, new_name: str):
        await self.execute(f"ALTER TABLE {self._pg_ident(app_label)}.{self._pg_ident(table_base_name)} RENAME COLUMN {self._pg_ident(old_name)} TO {self._pg_ident(new_name)}")
    
    def get_placeholder(self, index: int = 1) -> str:
        """PostgreSQL uses numbered placeholders like $1, $2, etc."""
        return f"${index}"
    
    def get_placeholders(self, count: int) -> str:
        """Get multiple numbered placeholders for PostgreSQL."""
        return ", ".join([f"${i+1}" for i in range(count)])

    # Full-text search condition builder
    def build_search_condition(
        self,
        table: str,
        search_info: Dict[str, Any],
        model_fields: Dict[str, Any],
        param_start: int,
        is_sqlite: bool = False,
    ) -> Tuple[str, list]:
        """Build a PostgreSQL full-text search condition using tsvector/tsquery.

        - Concatenates selected text fields into a single tsvector
        - Uses plainto_tsquery for the provided search string
        - Honors optional config in DATABASES['default']['OPTIONS']['TSVECTOR_CONFIG']
        """
        query = (search_info.get('query') or '').strip()
        if not query:
            return "", []

        # Determine fields to search (explicit > meta > inferred)
        fields = list(search_info.get('fields') or [])
        meta = search_info.get('meta') or {}
        if not fields:
            mf = meta.get('search_fields')
            if mf:
                fields = list(mf)
        if not fields:
            try:
                from ..fields import CharField, TextField
                for name, fld in (model_fields or {}).items():
                    if isinstance(fld, (CharField, TextField)):
                        fields.append(name)
            except Exception:
                # Fallback: include common text-like columns
                for name, fld in (model_fields or {}).items():
                    cls_name = getattr(getattr(fld, '__class__', None), '__name__', '')
                    if 'CharField' in cls_name or 'TextField' in cls_name:
                        fields.append(name)

        if not fields:
            return "", []

        # Build concatenated text expression: coalesce(f1,'') || ' ' || coalesce(f2,'') ...
        coalesced = [f"coalesce({f}, '')" for f in fields]
        concat_expr = " || ' ' || ".join(coalesced)

        # Optional text search config
        options = dict(self.config.get('OPTIONS', {}) or {})
        config = meta.get('search_config') or options.get('TSVECTOR_CONFIG')
        if config:
            tsvector_expr = f"to_tsvector('{config}', {concat_expr})"
            tsquery_expr = f"plainto_tsquery('{config}', {self.get_placeholder(param_start)})"
        else:
            tsvector_expr = f"to_tsvector({concat_expr})"
            tsquery_expr = f"plainto_tsquery({self.get_placeholder(param_start)})"

        condition = f"{tsvector_expr} @@ {tsquery_expr}"
        return condition, [query]

    def build_search_order_by(
        self,
        table: str,
        search_info: Dict[str, Any],
        model_fields: Dict[str, Any],
        param_start: int,
        is_sqlite: bool = False,
    ) -> Tuple[str, list]:
        """Build ORDER BY clause for Postgres search ranking using ts_rank."""
        query = (search_info.get('query') or '').strip()
        if not query:
            return "", []

        # Determine fields to search (explicit > meta > inferred)
        fields = list(search_info.get('fields') or [])
        meta = search_info.get('meta') or {}
        if not fields:
            mf = meta.get('search_fields')
            if mf:
                fields = list(mf)
        if not fields:
            try:
                from ..fields import CharField, TextField
                for name, fld in (model_fields or {}).items():
                    if isinstance(fld, (CharField, TextField)):
                        fields.append(name)
            except Exception:
                for name, fld in (model_fields or {}).items():
                    cls_name = getattr(getattr(fld, '__class__', None), '__name__', '')
                    if 'CharField' in cls_name or 'TextField' in cls_name:
                        fields.append(name)

        if not fields:
            return "", []

        coalesced = [f"coalesce({f}, '')" for f in fields]
        concat_expr = " || ' ' || ".join(coalesced)

        options = dict(self.config.get('OPTIONS', {}) or {})
        config = meta.get('search_config') or options.get('TSVECTOR_CONFIG')
        if config:
            tsvector_expr = f"to_tsvector('{config}', {concat_expr})"
            tsquery_placeholder = f"plainto_tsquery('{config}', {self.get_placeholder(param_start)})"
        else:
            tsvector_expr = f"to_tsvector({concat_expr})"
            tsquery_placeholder = f"plainto_tsquery({self.get_placeholder(param_start)})"

        # Optional per-field weights from Meta: {'title': 'A', 'body': 'B'}
        weights = meta.get('search_weights') or {}
        if weights:
            parts = []
            for f in fields:
                w = weights.get(f)
                if not w:
                    continue
                text_expr = f"coalesce({f}, '')"
                if config:
                    parts.append(f"setweight(to_tsvector('{config}', {text_expr}), '{w}')")
                else:
                    parts.append(f"setweight(to_tsvector({text_expr}), '{w}')")
            if parts:
                weighted_vec = " || ".join(parts)
                order_clause = f"ts_rank({weighted_vec}, {tsquery_placeholder}) DESC"
            else:
                order_clause = f"ts_rank({tsvector_expr}, {tsquery_placeholder}) DESC"
        else:
            order_clause = f"ts_rank({tsvector_expr}, {tsquery_placeholder}) DESC"
        return order_clause, [query]

    async def setup_full_text(self, app_label: str, table_base_name: str, search_meta: Dict[str, Any], fields: Dict[str, Any]):
        """Create tsvector column + GIN index + trigger for FTS if configured.

        Honors:
          - search_fields: iterable of columns to include (default: infer text fields)
          - search_config: text search config (e.g., 'english')
        """
        if not search_meta:
            return
        # Determine searchable fields
        cols = list(search_meta.get('search_fields') or [])
        if not cols:
            try:
                from ..fields import CharField, TextField
                for name, fld in (fields or {}).items():
                    if isinstance(fld, (CharField, TextField)):
                        cols.append(name)
            except Exception:
                for name, fld in (fields or {}).items():
                    cls_name = getattr(getattr(fld, '__class__', None), '__name__', '')
                    if 'CharField' in cls_name or 'TextField' in cls_name:
                        cols.append(name)
        if not cols:
            return

        schema = self._pg_ident(app_label)
        table = self._pg_ident(table_base_name)
        table_qualified = f"{schema}.{table}"
        config = search_meta.get('search_config')

        # Add search_vector column if not exists
        await self.execute(f"ALTER TABLE {table_qualified} ADD COLUMN IF NOT EXISTS search_vector tsvector")

        # Build concatenated text expression
        coalesced = " || ' ' || ".join([f"coalesce({self._pg_ident(c)}, '')" for c in cols])
        if config:
            set_expr = f"to_tsvector('{config}', {coalesced})"
        else:
            set_expr = f"to_tsvector({coalesced})"

        await self.execute(f"UPDATE {table_qualified} SET search_vector = {set_expr}")
        await self.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_base_name}_search_vector ON {table_qualified} USING GIN (search_vector)")

        # Create/replace update function and trigger
        func_name = f"{table_base_name}_tsvector_update"
        func_ident = f"{schema}.\"{func_name}\""
        new_expr = set_expr.replace("coalesce(", "coalesce(NEW.")  # prefix with NEW.
        # Replace identifiers more safely
        new_expr = " || ' ' || ".join([f"coalesce(NEW.{c}, '')" for c in cols])
        if config:
            new_expr = f"to_tsvector('{config}', {new_expr})"
        else:
            new_expr = f"to_tsvector({new_expr})"

        func_sql = (
            f"CREATE OR REPLACE FUNCTION {func_ident}() RETURNS trigger AS $$\n"
            f"BEGIN\n"
            f"  NEW.search_vector := {new_expr};\n"
            f"  RETURN NEW;\n"
            f"END\n"
            f"$$ LANGUAGE plpgsql;"
        )
        await self.execute(func_sql)
        await self.execute(f"DROP TRIGGER IF EXISTS {func_name} ON {table_qualified}")
        await self.execute(
            f"CREATE TRIGGER {func_name} BEFORE INSERT OR UPDATE ON {table_qualified} FOR EACH ROW EXECUTE FUNCTION {func_ident}()"
        )
