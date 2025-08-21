"""
Model base class and metaclass for collecting fields.

Behavior highlights (SQLite and PostgreSQL):
- Adds a default primary key when none is declared: `id = CharField(primary_key=True)`.
- Auto-generates a primary key value if not provided on create:
  - For the default CharField primary key, a UUID4 hex string is generated.
  - If a custom primary key is declared by the user, it is respected (no auto-generation).

This provides compatibility for imports like:
    from core.db.models import Model
"""
from __future__ import annotations

from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING
import inspect
import datetime
from .connection import get_databases, DatabaseType
from .queryset import QuerySet
from .fields import BaseField, CharField


class classproperty(property):
    def __get__(self, owner_self, owner_cls):
        return self.fget(owner_cls)


class ModelBase(type):
    def __new__(mcls, name, bases, attrs):
        fields: Dict[str, BaseField] = {}
        for base in bases:
            if hasattr(base, "_fields"):
                fields.update(getattr(base, "_fields"))

        own_fields = {k: v for k, v in list(attrs.items()) if isinstance(v, BaseField)}
        for k in own_fields:
            attrs.pop(k)

        cls = super().__new__(mcls, name, bases, attrs)
        fields.update(own_fields)

        # Default primary key: if no explicit PK is declared, add a CharField PK named "id".
        # The value will be auto-generated on save if not provided by the user.
        if "id" not in fields and not any(getattr(f, 'primary_key', False) for f in fields.values()):
            fields["id"] = CharField(primary_key=True)

        for fname, field in fields.items():
            if hasattr(field, 'contribute_to_class'):
                field.contribute_to_class(cls, fname)
            else:
                setattr(field, '_name', fname)

        cls._fields = fields
        
        return cls


class Model(metaclass=ModelBase):
    _fields: Dict[str, BaseField]

    def __init__(self, **kwargs: Any):
        for name, field in self._fields.items():
            if name in kwargs:
                value = kwargs[name]
            else:
                default = getattr(field, 'default', None)
                value = default() if callable(default) else default
            setattr(self, name, value)

    @classmethod
    def describe(cls) -> Dict[str, Any]:
        return {
            'model': cls.__name__,
            'fields': {name: field.describe() for name, field in cls._fields.items()},
        }

    @classmethod
    def get_app_label(cls) -> str:
        module = inspect.getmodule(cls)
        if not module:
            raise ValueError(f"Could not determine module for {cls.__name__}")

        module_path = module.__name__
        file_path = getattr(module, '__file__', '') or ''

        # 1) If located under an apps/ directory, use that app folder name
        if 'apps/' in file_path or 'apps\\' in file_path:
            sep = '/' if 'apps/' in file_path else '\\'
            parts = file_path.split(f'apps{sep}')
            if len(parts) > 1:
                return parts[1].split(sep)[0]

        # 2) If the module path includes an 'apps' package, use the next segment
        parts = module_path.split('.')
        if 'apps' in parts:
            idx = parts.index('apps')
            if len(parts) > idx + 1:
                return parts[idx + 1]

        # 3) Heuristic for tests: if file path contains a tests/ directory,
        #    use the parent directory name as the app label (project package)
        if file_path:
            import os
            norm = file_path.replace('\\', '/')
            segments = [s for s in norm.split('/') if s]
            if 'tests' in segments:
                t_idx = segments.index('tests')
                if t_idx > 0:
                    return segments[t_idx - 1]

        # 4) Fallback to the top-level module name
        return parts[0]

    @classmethod
    def get_table_name(cls) -> str:
        table_name = cls.__name__
        snake = ''.join(['_' + c.lower() if c.isupper() else c.lower() for c in table_name]).lstrip('_')
        return f"{cls.get_app_label()}_{snake}"

    @classmethod
    def _get_parsed_table_name(cls) -> Tuple[str, str]:
        schema = cls.get_app_label()
        full = cls.get_table_name()
        prefix = f"{schema}_"
        if full.startswith(prefix):
            return schema, full[len(prefix):]
        return schema, full

    @classmethod
    def _quote(cls, name: str) -> str:
        if name.startswith('"') and name.endswith('"'):
            return name
        return f'"{name}"'

    async def save(self, create: bool = True, using: Optional[str] = None):
        """Persist the model instance to the database.

        - On insert (create=True), if there is exactly one primary key field and its
          value is missing/None, a value may be auto-generated:
            - When the PK field is a CharField (the default), a time-sortable ID
              is generated (ULID by default; UUIDv7 if available) and set on the
              instance prior to INSERT. This yields better index locality across
              SQLite and PostgreSQL.
            - If the user declared a custom primary key, its value is not generated
              automatically; the user is expected to supply it or configure a DB-side
              default.
        - On update (create=False), all fields are written as-is.
        """
        alias = using or 'default'
        db = await get_databases().get_connection(alias)
        is_pg = getattr(db, 'db_type', None) == DatabaseType.POSTGRES
        schema, table = self._get_parsed_table_name()
        table_ident = f"{self._quote(schema)}.{self._quote(table)}" if is_pg else self._quote(f"{schema}_{table}")

        # Auto-generate a primary key value if appropriate (single PK, missing value).
        try:
            pk_fields = [name for name, f in self._fields.items() if getattr(f, 'primary_key', False)]
            if len(pk_fields) == 1:
                pk_name = pk_fields[0]
                pk_field = self._fields[pk_name]
                if getattr(self, pk_name, None) in (None, ""):
                    from .fields import CharField  # localized import to avoid cycles
                    if isinstance(pk_field, CharField):
                        from ..utils.ids import generate_time_sortable_id
                        setattr(self, pk_name, generate_time_sortable_id())
                    # For non-CharField PKs, defer to user-configured DB defaults.
        except Exception:
            # Never allow PK generation logic to crash save(); fall through to normal flow.
            pass

        # Prepare columns/values
        cols = []
        vals = []
        for fname, field in self._fields.items():
            db_col = getattr(field, 'db_column', None) or fname
            val = getattr(self, fname, None)
            if val is None and getattr(field, 'default', None) is not None:
                val = field.default() if callable(field.default) else field.default
            if isinstance(val, datetime.datetime) and not is_pg:
                val = val.isoformat()
            # Serialize JSON fields
            if hasattr(field, '__class__') and 'JSONField' in field.__class__.__name__:
                if isinstance(val, (dict, list)):
                    import json
                    val = json.dumps(val)
            cols.append(self._quote(db_col))
            vals.append(val)

        if is_pg:
            placeholders = ', '.join([f"${i+1}" for i in range(len(vals))])
        else:
            placeholders = ', '.join(['?'] * len(vals))

        sql = f"INSERT INTO {table_ident} ({', '.join(cols)}) VALUES ({placeholders})"
        await db.execute(sql, vals if is_pg else tuple(vals))
        await db.commit()

    @classproperty
    def objects(cls) -> QuerySet:
        """Return a QuerySet bound to the model's table."""
        return QuerySet(cls)

    class _Manager:
        def __init__(self, model_cls: type['Model']):
            self.model_cls = model_cls

        async def create(self, **kwargs: Any) -> 'Model':
            obj = self.model_cls(**kwargs)
            await obj.save(create=True)
            return obj

    @classmethod
    def _get_manager(cls) -> '_Manager':
        return cls._Manager(cls)
