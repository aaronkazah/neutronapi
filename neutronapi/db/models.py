"""
Model base class and metaclass for collecting fields.

This provides compatibility for imports like:
    from core.db.models import Model
"""
from __future__ import annotations

from typing import Dict, Any, Optional, Tuple
import inspect
import datetime
from .connection import get_databases, DatabaseType

from .fields import BaseField, CharField


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

        if "id" not in fields:
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
        if 'apps/' in file_path:
            parts = file_path.split('apps/')
            if len(parts) > 1:
                return parts[1].split('/')[0]
        parts = module_path.split('.')
        if 'apps' in parts:
            idx = parts.index('apps')
            if len(parts) > idx + 1:
                return parts[idx + 1]
        # Fallback to top-level module
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
        alias = using or 'default'
        db = await get_databases().get_connection(alias)
        is_pg = getattr(db, 'db_type', None) == DatabaseType.POSTGRES
        schema, table = self._get_parsed_table_name()
        table_ident = f"{self._quote(schema)}.{self._quote(table)}" if is_pg else self._quote(f"{schema}_{table}")

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
            cols.append(self._quote(db_col))
            vals.append(val)

        if is_pg:
            placeholders = ', '.join([f"${i+1}" for i in range(len(vals))])
        else:
            placeholders = ', '.join(['?'] * len(vals))

        sql = f"INSERT INTO {table_ident} ({', '.join(cols)}) VALUES ({placeholders})"
        await db.execute(sql, vals if is_pg else tuple(vals))
        await db.commit()

    class _Manager:
        def __init__(self, model_cls):
            self.model_cls = model_cls

        async def create(self, **kwargs):
            obj = self.model_cls(**kwargs)
            await obj.save(create=True)
            return obj

    @classmethod
    def _get_manager(cls):
        return cls._Manager(cls)

    @classmethod
    def objects(cls):  # type: ignore
        return cls._get_manager()
