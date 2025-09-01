import json
import datetime
import re
from typing import Optional, Dict, List, Any, Tuple

from .base import BaseProvider


class SQLiteProvider(BaseProvider):
    """Async SQLite provider using aiosqlite with built-in schema operations."""

    async def _ensure_connected(self):
        if getattr(self, 'conn', None) is None:
            await self.connect()

    async def connect(self):
        try:
            import aiosqlite
        except ImportError:
            raise ImportError("aiosqlite required for SQLite support")

        db_path = self.config.get('NAME', 'temp.db')

        import os
        # Support Path-like objects and strings
        db_path_fs = os.fspath(db_path)
        db_dir = os.path.dirname(db_path_fs)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        # Allow passing through selected sqlite options via DATABASES['default']['OPTIONS']
        options = dict(self.config.get('OPTIONS', {}) or {})
        connect_kwargs = {}
        for key in (
            'timeout', 'detect_types', 'isolation_level', 'check_same_thread',
            'cached_statements', 'uri'
        ):
            if key in options:
                connect_kwargs[key] = options[key]

        self.conn = await aiosqlite.connect(db_path_fs, **connect_kwargs)
        self.conn.row_factory = aiosqlite.Row

        # Default pragmas (can be overridden via OPTIONS['PRAGMAS'])
        default_pragmas = {
            'journal_mode': 'WAL',
            'synchronous': 'NORMAL',
            'cache_size': 10000,
            'temp_store': 'memory',
            'mmap_size': 268435456,
        }
        user_pragmas = dict(options.get('PRAGMAS', {}) or {})
        pragmas = {**default_pragmas, **user_pragmas}

        # Apply PRAGMAs
        for k, v in pragmas.items():
            # Build PRAGMA statement; allow raw tokens (e.g., WAL, NORMAL) or numbers
            if isinstance(v, str) and not v.isnumeric():
                stmt = f"PRAGMA {k}={v}"
            else:
                stmt = f"PRAGMA {k}={int(v)}"
            await self.conn.execute(stmt)

        await self.create_tables()

    async def disconnect(self):
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def execute(self, query: str, params: Tuple = ()) -> Any:
        await self._ensure_connected()
        sqlite_query = self._convert_postgres_params(query)
        cursor = await self.conn.execute(sqlite_query, params)
        await self.conn.commit()
        return cursor

    def _convert_postgres_params(self, query: str) -> str:
        query = query.replace(' ILIKE ', ' LIKE ').replace(' NOT ILIKE ', ' NOT LIKE ')
        return re.sub(r'\$\d+', lambda m: '?', query)

    async def fetchone(self, query: str, params: Tuple = ()) -> Optional[Dict[str, Any]]:
        await self._ensure_connected()
        sqlite_query = self._convert_postgres_params(query)
        cursor = await self.conn.execute(sqlite_query, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetchall(self, query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        await self._ensure_connected()
        sqlite_query = self._convert_postgres_params(query)
        cursor = await self.conn.execute(sqlite_query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def create_tables(self):
        await self._ensure_connected()
        sql = """
        CREATE TABLE IF NOT EXISTS objects (
            id TEXT PRIMARY KEY,
            key TEXT UNIQUE NOT NULL,
            name TEXT,
            kind TEXT NOT NULL DEFAULT 'file',
            meta TEXT,
            store TEXT,
            connections TEXT,
            folder TEXT,
            parent TEXT,
            sha256 TEXT,
            size INTEGER,
            content_type TEXT,
            latest_revision TEXT,
            vec BLOB,
            created TIMESTAMP,
            modified TIMESTAMP
        )
        """

        await self.conn.execute(sql)
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_objects_key ON objects(key)",
            "CREATE INDEX IF NOT EXISTS idx_objects_folder ON objects(folder)",
            "CREATE INDEX IF NOT EXISTS idx_objects_parent ON objects(parent)",
            "CREATE INDEX IF NOT EXISTS idx_objects_kind ON objects(kind)",
            "CREATE INDEX IF NOT EXISTS idx_objects_modified ON objects(modified)",
        ]
        for idx in indexes:
            await self.conn.execute(idx)
        await self.conn.commit()

    def serialize(self, data: Any) -> Optional[str]:
        if data is None:
            return None
        def default_serializer(o):
            if isinstance(o, datetime.datetime):
                return o.isoformat()
            raise TypeError()
        return json.dumps(data, default=default_serializer)

    def deserialize(self, data: str) -> Any:
        return json.loads(data) if data is not None else None

    def convert_query_param(self, value: Any, field) -> Any:
        """Convert query parameter values for SQLite-specific requirements."""
        # For DateTimeField, convert datetime objects to ISO strings for TEXT storage
        if hasattr(field, '__class__') and 'DateTimeField' in field.__class__.__name__:
            if isinstance(value, datetime.datetime):
                return value.isoformat()
        return value

    # Schema operations (merged)
    def _process_default_value(self, default: Any) -> str:
        value = default() if callable(default) else default
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "True" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, datetime.datetime):
            return f"'{value.isoformat()}'"
        if isinstance(value, (dict, list)):
            return "'" + json.dumps(value).replace("'", "''") + "'"
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
        return "'" + str(value).replace("'", "''") + "'"

    async def get_column_info(self, table_name: str) -> List[dict]:
        await self._ensure_connected()
        if not await self.table_exists(table_name):
            raise ValueError(f"Table '{table_name}' does not exist.")
        cursor = await self.conn.execute(f'PRAGMA table_info("{table_name}")')
        rows = await cursor.fetchall()
        return [
            {
                "cid": row[0],
                "name": row[1],
                "type": row[2],
                "notnull": bool(row[3]),
                "dflt_value": row[4],
                "pk": bool(row[5]),
            }
            for row in rows
        ]

    async def table_exists(self, table_name: str) -> bool:
        await self._ensure_connected()
        row = await self.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        return row is not None

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
            BooleanField: "INTEGER",
            DateTimeField: "TEXT",
            JSONField: "TEXT",
            VectorField: "BLOB",
            BinaryField: "BLOB",
            EnumField: "TEXT",
            FloatField: "REAL",
        }
        return mapping.get(type(field), "TEXT")

    async def column_exists(self, app_label: str, table_base_name: str, column_name: str) -> bool:
        table_name = f"{app_label}_{table_base_name}"
        try:
            columns = await self.get_column_info(table_name)
            return any(col["name"] == column_name for col in columns)
        except Exception:
            return False

    async def create_table(self, app_label: str, table_base_name: str, fields: List[Tuple[str, Any]]):
        await self._ensure_connected()
        table_name = f"{app_label}_{table_base_name}"
        if await self.table_exists(table_name):
            return
        field_defs = []
        primary_keys = []
        pk_count = sum(1 for _, f in fields if getattr(f, 'primary_key', False))
        for name, field in fields:
            coltype = self.get_column_type(field)
            qname = f'"{name}"'
            parts = [f"{qname} {coltype}"]
            if getattr(field, 'primary_key', False):
                if pk_count == 1:
                    parts.append("PRIMARY KEY")
                else:
                    primary_keys.append(qname)
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
        if pk_count > 1 and primary_keys:
            field_defs.append(f"PRIMARY KEY ({', '.join(primary_keys)})")
        await self.execute(f"CREATE TABLE \"{table_name}\" ({', '.join(field_defs)})")

    async def drop_table(self, app_label: str, table_base_name: str):
        await self._ensure_connected()
        await self.execute(f"DROP TABLE IF EXISTS \"{app_label}_{table_base_name}\"")

    async def add_column(self, app_label: str, table_base_name: str, field_name: str, field: Any):
        await self._ensure_connected()
        table_name = f"{app_label}_{table_base_name}"
        if not await self.table_exists(table_name):
            raise ValueError(f"Cannot add column, table '{table_name}' does not exist.")
        if await self.column_exists(app_label, table_base_name, field_name):
            return
        coltype = self.get_column_type(field)
        qfield = f'"{field_name}"'
        parts = [f"{qfield} {coltype}"]
        if not getattr(field, 'null', False):
            parts.append("NOT NULL")
        if getattr(field, 'unique', False):
            parts.append("UNIQUE")
        default = getattr(field, 'default', None)
        # In SQLite, adding a NOT NULL column with no default is invalid.
        # Provide a safe default based on column type to allow the operation.
        if default is None and not getattr(field, 'null', False):
            if coltype in ("TEXT",):
                default = ""
            elif coltype in ("INTEGER",):
                default = 0
            elif coltype in ("REAL",):
                default = 0.0
            elif coltype in ("BLOB",):
                default = None  # remains NULL; NOT NULL BLOB rarely added without default
            else:
                default = ""
        if default is not None:
            default_sql = self._process_default_value(default)
            if default_sql != "NULL":
                parts.append(f"DEFAULT {default_sql}")
        await self.execute(f"ALTER TABLE \"{table_name}\" ADD COLUMN {' '.join(parts)}")

    async def alter_column(self, app_label: str, table_base_name: str, field_name: str, field: Any):
        await self._ensure_connected()
        table_name = f"{app_label}_{table_base_name}"
        columns = await self.get_column_info(table_name)
        new_fields = []
        names_for_copy = []
        found = False
        for col in columns:
            nm = col['name']
            names_for_copy.append(f'"{nm}"')
            if nm == field_name:
                new_fields.append((field_name, field))
                found = True
            else:
                new_fields.append((nm, self._create_field_from_column(col)))
        if not found:
            raise ValueError(f"Column '{field_name}' to alter not found in table '{table_name}' during rebuild.")
        temp_base = f"{table_base_name}_alter_temp"
        await self.create_table(app_label, temp_base, new_fields)
        cols = ", ".join(names_for_copy)
        await self.execute(f"INSERT INTO \"{app_label}_{temp_base}\" ({cols}) SELECT {cols} FROM \"{table_name}\"")
        await self.execute(f"DROP TABLE \"{table_name}\"")
        await self.rename_table(app_label, temp_base, app_label, table_base_name)

    async def remove_column(self, app_label: str, table_base_name: str, field_name: str):
        await self._ensure_connected()
        table_name = f"{app_label}_{table_base_name}"
        columns = await self.get_column_info(table_name)
        remaining = []
        names = []
        for col in columns:
            if col['name'] != field_name:
                remaining.append((col['name'], self._create_field_from_column(col)))
                names.append(f'"{col["name"]}"')
        if not remaining:
            raise ValueError(f"Cannot remove last column '{field_name}' from table '{table_name}'.")
        temp_base = f"{table_base_name}_remove_temp"
        await self.create_table(app_label, temp_base, remaining)
        cols = ", ".join(names)
        await self.execute(f"INSERT INTO \"{app_label}_{temp_base}\" ({cols}) SELECT {cols} FROM \"{table_name}\"")
        await self.execute(f"DROP TABLE \"{table_name}\"")
        await self.rename_table(app_label, temp_base, app_label, table_base_name)

    async def rename_table(self, old_app_label: str, old_base: str, new_app_label: str, new_base: str):
        await self._ensure_connected()
        old = f"{old_app_label}_{old_base}"
        new = f"{new_app_label}_{new_base}"
        await self.execute(f"ALTER TABLE \"{old}\" RENAME TO \"{new}\"")

    async def rename_column(self, app_label: str, table_base_name: str, old_name: str, new_name: str):
        await self._ensure_connected()
        table_name = f"{app_label}_{table_base_name}"
        version_row = await self.fetchone("SELECT sqlite_version()")
        sqlite_version_str = list(version_row.values())[0] if isinstance(version_row, dict) else version_row[0]
        try:
            version_tuple = tuple(map(int, str(sqlite_version_str).split('.')))
        except Exception:
            version_tuple = (3, 25, 0)
        if version_tuple >= (3, 25, 0):
            await self.execute(f"ALTER TABLE \"{table_name}\" RENAME COLUMN \"{old_name}\" TO \"{new_name}\"")
            return
        # Fallback: rebuild
        columns = await self.get_column_info(table_name)
        new_fields = []
        select_old = []
        insert_new = []
        for col in columns:
            current = col['name']
            select_old.append(f'"{current}"')
            field = self._create_field_from_column(col)
            if current == old_name:
                new_fields.append((new_name, field))
                insert_new.append(f'"{new_name}"')
            else:
                new_fields.append((current, field))
                insert_new.append(f'"{current}"')
        temp_base = f"{table_base_name}_rename_temp"
        await self.create_table(app_label, temp_base, new_fields)
        await self.execute(
            f"INSERT INTO \"{app_label}_{temp_base}\" ({', '.join(insert_new)}) SELECT {', '.join(select_old)} FROM \"{table_name}\""
        )
        await self.execute(f"DROP TABLE \"{table_name}\"")
        await self.rename_table(app_label, temp_base, app_label, table_base_name)

    def _parse_sqlite_default(self, raw_default: Optional[str], column_type: str) -> Any:
        try:
            if raw_default is None:
                return None
            up = str(raw_default).upper()
            if up == "NULL":
                return None
            if up == "CURRENT_TIMESTAMP":
                return datetime.datetime.now
            if up == "CURRENT_DATE":
                return datetime.date.today
            if up == "CURRENT_TIME":
                return lambda: datetime.datetime.now().time()
            if str(raw_default).startswith("'") and str(raw_default).endswith("'"):
                inner_value = str(raw_default)[1:-1]
                return inner_value.replace("''", "'")
            if column_type.upper() in ("INTEGER", "INT", "REAL", "FLOAT", "BOOLEAN"):
                if str(raw_default).lower() == "True":
                    return True
                if str(raw_default).lower() == "False":
                    return False
                try:
                    val = int(raw_default)
                    if column_type.upper() == "BOOLEAN":
                        return bool(val)
                    return val
                except ValueError:
                    return float(raw_default)
            if column_type.upper() == "BLOB":
                return None
            return raw_default
        except Exception:
            return raw_default

    def _create_field_from_column(self, column_info: dict):
        from ..fields import (
            BooleanField,
            VectorField,
            CharField,
            IntegerField,
            DateTimeField,
            FloatField,
            BinaryField,
        )
        col_name = column_info["name"]
        col_type_raw = column_info["type"]
        col_type_upper = col_type_raw.upper()
        parsed_default = self._parse_sqlite_default(column_info["dflt_value"], col_type_raw)
        potential_args = {
            "null": not column_info["notnull"],
            "default": parsed_default,
            "primary_key": bool(column_info["pk"]),
            "max_length": None,
        }
        field_cls = CharField
        if col_type_upper in ("TEXT", "VARCHAR", "CHAR", "DATETIME"):
            field_cls = CharField
            if col_type_upper == "DATETIME":
                field_cls = DateTimeField
            import re as _re
            match = _re.match(r"VARCHAR\((\d+)\)", col_type_upper)
            if match:
                potential_args["max_length"] = int(match.group(1))
        elif col_type_upper == "INTEGER":
            field_cls = IntegerField
            if isinstance(parsed_default, bool):
                field_cls = BooleanField
        elif col_type_upper == "REAL":
            field_cls = FloatField
        elif col_type_upper == "BLOB":
            field_cls = BinaryField
            if col_name == "vector":
                field_cls = VectorField
        init_args = {k: v for k, v in potential_args.items() if v is not None or k in ("null", "primary_key")}
        if field_cls is CharField and potential_args.get("max_length") is not None:
            init_args["max_length"] = potential_args["max_length"]
        return field_cls(**init_args)
    
    def get_placeholder(self, index: int = 1) -> str:
        """SQLite uses ? placeholders."""
        return "?"
    
    def get_placeholders(self, count: int) -> str:
        """Get multiple ? placeholders for SQLite."""
        return ", ".join(["?"] * count)

    # Full-text search condition builder (FTS5 or LIKE fallback)
    def build_search_condition(
        self,
        table: str,
        search_info: Dict[str, Any],
        model_fields: Dict[str, Any],
        param_start: int,
        is_sqlite: bool = True,
    ) -> Tuple[str, list]:
        """Build an SQLite full-text search condition.

        Uses FTS5 MATCH against a configured FTS virtual table when available,
        otherwise falls back to a case-insensitive LIKE across detected text fields.

        Configuration (optional): DATABASES['default']['OPTIONS']['FTS'] can specify:
          - table: name of the FTS5 table (default: f"{table}_fts")
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
                for name, fld in (model_fields or {}).items():
                    cls_name = getattr(getattr(fld, '__class__', None), '__name__', '')
                    if 'CharField' in cls_name or 'TextField' in cls_name:
                        fields.append(name)

        if not fields:
            return "", []

        options = dict(self.config.get('OPTIONS', {}) or {})
        fts_cfg = options.get('FTS')
        # Model Meta can enable/override FTS table name
        meta_fts = meta.get('sqlite_fts')
        if meta_fts is not None:
            fts_cfg = meta_fts
        fts_table = None
        if isinstance(fts_cfg, dict):
            # If dict provided, honor explicit name or default to <table>_fts
            fts_table = fts_cfg.get('table') or f"{table}_fts"
        elif fts_cfg:
            # Any truthy non-dict also enables default
            fts_table = f"{table}_fts"

        if fts_table:
            # Build MATCH query; if specific fields provided, constrain via column qualifiers.
            # E.g., name:foo OR description:foo
            if search_info.get('fields'):
                match_expr = " OR ".join([f"{col}:{query}" for col in fields])
            else:
                match_expr = query
            placeholder = self.get_placeholder(param_start)
            condition = f"rowid IN (SELECT rowid FROM {fts_table} WHERE {fts_table} MATCH {placeholder})"
            return condition, [match_expr]

        # Fallback: LIKE across text fields (case-insensitive)
        conditions: List[str] = []
        params: List[Any] = []
        for col in fields:
            placeholder = self.get_placeholder(param_start)
            # Use LOWER(field) LIKE LOWER(?) for case-insensitivity
            conditions.append(f"LOWER(\"{col}\") LIKE LOWER({placeholder})")
            params.append(f"%{query}%")
        return " OR ".join(conditions), params

    def build_search_order_by(
        self,
        table: str,
        search_info: Dict[str, Any],
        model_fields: Dict[str, Any],
        param_start: int,
        is_sqlite: bool = True,
    ) -> Tuple[str, list]:
        """Build ORDER BY clause for SQLite FTS when available.

        Uses a correlated subselect to compute bm25 score against the FTS table
        for each row. If FTS isn't configured, returns an empty clause.
        """
        query = (search_info.get('query') or '').strip()
        if not query:
            return "", []

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

        options = dict(self.config.get('OPTIONS', {}) or {})
        fts_cfg = options.get('FTS')
        meta_fts = meta.get('sqlite_fts')
        if meta_fts is not None:
            fts_cfg = meta_fts
        fts_table = None
        if isinstance(fts_cfg, dict):
            fts_table = fts_cfg.get('table') or f"{table}_fts"
        elif fts_cfg:
            fts_table = f"{table}_fts"
        if not fts_table:
            return "", []

        # Build the same match expression as condition
        if search_info.get('fields'):
            match_expr = " OR ".join([f"{col}:{query}" for col in fields])
        else:
            match_expr = query
        placeholder = self.get_placeholder(param_start)
        # Correlated subselect computes bm25 for matching rowid; ASC => best score first
        order_clause = (
            f"(SELECT bm25({fts_table}) FROM {fts_table} "
            f"WHERE {fts_table}.rowid = {table}.rowid AND {fts_table} MATCH {placeholder}) ASC"
        )
        return order_clause, [match_expr]

    async def setup_full_text(self, app_label: str, table_base_name: str, search_meta: dict, fields: Dict[str, Any]):
        """Create FTS5 virtual table and triggers if enabled via search_meta.

        Expects search_meta to optionally include:
          - sqlite_fts: truthy or {'table': name}
          - search_fields: iterable of column names to include in FTS
        """
        if not search_meta:
            return
        fts_cfg = search_meta.get('sqlite_fts')
        if not fts_cfg:
            return
        base_table = f"{app_label}_{table_base_name}"
        # Determine fts table name
        if isinstance(fts_cfg, dict) and 'table' in fts_cfg:
            fts_table = fts_cfg['table']
        else:
            fts_table = f"{base_table}_fts"

        # Determine fields for FTS
        fts_fields = list(search_meta.get('search_fields') or [])
        if not fts_fields:
            # Infer Char/Text fields
            try:
                from ..fields import CharField, TextField
                for name, fld in (fields or {}).items():
                    if isinstance(fld, (CharField, TextField)):
                        fts_fields.append(name)
            except Exception:
                for name, fld in (fields or {}).items():
                    cls_name = getattr(getattr(fld, '__class__', None), '__name__', '')
                    if 'CharField' in cls_name or 'TextField' in cls_name:
                        fts_fields.append(name)
        if not fts_fields:
            return

        cols = ", ".join(fts_fields)
        # Create FTS table with content binding for rowid sync
        await self.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS \"{fts_table}\" USING fts5({cols}, content='\"{base_table}\"', content_rowid='rowid')"
        )

        # Triggers to keep content synchronized
        cols_insert = ", ".join(fts_fields)
        new_cols_vals = ", ".join([f"new.{c}" for c in fts_fields])
        old_cols_vals = ", ".join([f"old.{c}" for c in fts_fields])

        await self.execute(
            f"CREATE TRIGGER IF NOT EXISTS {base_table}_ai AFTER INSERT ON \"{base_table}\" BEGIN "
            f"INSERT INTO \"{fts_table}\"(rowid, {cols_insert}) VALUES (new.rowid, {new_cols_vals}); END;"
        )
        await self.execute(
            f"CREATE TRIGGER IF NOT EXISTS {base_table}_ad AFTER DELETE ON \"{base_table}\" BEGIN "
            f"INSERT INTO \"{fts_table}\"({fts_table}, rowid, {cols_insert}) VALUES('delete', old.rowid, {old_cols_vals}); END;"
        )
        await self.execute(
            f"CREATE TRIGGER IF NOT EXISTS {base_table}_au AFTER UPDATE ON \"{base_table}\" BEGIN "
            f"INSERT INTO \"{fts_table}\"({fts_table}, rowid, {cols_insert}) VALUES('delete', old.rowid, {old_cols_vals}); "
            f"INSERT INTO \"{fts_table}\"(rowid, {cols_insert}) VALUES (new.rowid, {new_cols_vals}); END;"
        )
