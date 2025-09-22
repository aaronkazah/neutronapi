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

from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .queryset import QuerySet

Self = TypeVar('Self', bound='Model')

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
            if hasattr(base, "_neutronapi_fields_"):
                fields.update(getattr(base, "_neutronapi_fields_"))

        own_fields = {k: v for k, v in list(attrs.items()) if isinstance(v, BaseField)}
        
        # Validate that no fields use reserved NeutronAPI internal names
        for field_name in own_fields:
            if field_name.startswith('_neutronapi_') and field_name.endswith('_'):
                raise ValueError(
                    f"Field name '{field_name}' is reserved for NeutronAPI internal use. "
                    f"Names matching pattern '_neutronapi_*_' are not allowed."
                )
        
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

        cls._neutronapi_fields_ = fields
        
        return cls


class Model(metaclass=ModelBase):
    _neutronapi_fields_: Dict[str, BaseField]
    DoesNotExist = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.DoesNotExist = type("DoesNotExist", (Exception,), {
            '__module__': cls.__module__,
            '__qualname__': f'{cls.__qualname__}.DoesNotExist'
        })

    def __init__(self, **kwargs: Any):
        # pk tracks if this came from database - None = fresh object
        self.pk = None

        for name, field in self._neutronapi_fields_.items():
            if name in kwargs:
                value = kwargs[name]
                # Convert enum to its value if needed
                value = self._convert_enum_value(value)
                # Use field's from_db method to properly deserialize values from database
                if hasattr(field, 'from_db') and callable(field.from_db):
                    try:
                        value = field.from_db(value)
                    except Exception:
                        # If from_db fails, use the raw value
                        pass
            else:
                default = getattr(field, 'default', None)
                value = default() if callable(default) else default
            setattr(self, name, value)

    def _convert_enum_value(self, value):
        """Convert enum instances to their values for database storage."""
        import enum
        if isinstance(value, enum.Enum):
            return value.value
        return value

    @classmethod
    def describe(cls) -> Dict[str, Any]:
        return {
            'model': cls.__name__,
            'fields': {name: field.describe() for name, field in cls._neutronapi_fields_.items()},
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

    async def save(self, create: Optional[bool] = None, using: Optional[str] = None):
        """Persist the model instance to the database.

        - Default behavior: If ``create`` is None, INSERT when primary key is missing,
          otherwise UPDATE the existing row by primary key. This ensures that calling
          ``instance.save()`` on a loaded object does not create duplicates.
        - On insert (create=True), if there is exactly one primary key field and its
          value is missing/None, a value may be auto-generated:
            - When the PK field is a CharField (the default), a time-sortable ID
              is generated (ULID by default; UUIDv7 if available) and set prior to INSERT.
            - If a custom PK is declared, it is respected and not auto-generated.
        - On update (create=False), only non-PK fields are updated via a single UPDATE
          statement with a WHERE on the primary key.
        """
        alias = using or 'default'
        db = await get_databases().get_connection(alias)
        is_pg = getattr(db, 'db_type', None) == DatabaseType.POSTGRES
        schema, table = self._get_parsed_table_name()
        table_ident = f"{self._quote(schema)}.{self._quote(table)}" if is_pg else self._quote(f"{schema}_{table}")

        # Determine primary key
        pk_fields = [name for name, f in self._neutronapi_fields_.items() if getattr(f, 'primary_key', False)]
        pk_name = pk_fields[0] if len(pk_fields) == 1 else None

        # Decide insert vs update if not explicitly set
        if create is None:
            # Simple logic: if pk is set, it came from DB → UPDATE, else → INSERT
            create = self.pk is None

        if create:
            # Auto-generate a primary key value if appropriate (single PK, missing value).
            try:
                if pk_name is not None:
                    pk_field = self._neutronapi_fields_[pk_name]
                    if getattr(self, pk_name, None) in (None, ""):
                        from .fields import CharField  # localized import to avoid cycles
                        if isinstance(pk_field, CharField):
                            from ..utils.ids import generate_time_sortable_id
                            setattr(self, pk_name, generate_time_sortable_id())
                        # For non-CharField PKs, defer to user-configured DB defaults.
            except Exception:
                # Never allow PK generation logic to crash save(); fall through to normal flow.
                pass

        if create:
            # Prepare columns/values for INSERT
            cols = []
            vals = []
            for fname, field in self._neutronapi_fields_.items():
                db_col = getattr(field, 'db_column', None) or fname
                val = getattr(self, fname, None)
                if val is None and getattr(field, 'default', None) is not None:
                    val = field.default() if callable(field.default) else field.default
                # Convert enum to value
                val = self._convert_enum_value(val)
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

            # Handle conflicts: UPSERT instead of failing on duplicate
            if is_pg:
                # PostgreSQL: ON CONFLICT DO UPDATE
                update_cols = [f"{col} = EXCLUDED.{col}" for col in cols if col != self._quote(pk_name)]
                sql = f"INSERT INTO {table_ident} ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT ({self._quote(pk_name)}) DO UPDATE SET {', '.join(update_cols)}"
            else:
                # SQLite: ON CONFLICT DO UPDATE (safer than REPLACE)
                update_cols = [f"{col} = excluded.{col}" for col in cols if col != self._quote(pk_name)]
                sql = f"INSERT INTO {table_ident} ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT({self._quote(pk_name)}) DO UPDATE SET {', '.join(update_cols)}"
            await db.execute(sql, vals if is_pg else tuple(vals))
            await db.commit()

            # After successful INSERT, set pk to primary key value for future saves
            self.pk = self.id
            return

        # UPDATE path (create is False)
        if not pk_name:
            raise ValueError("Cannot update without a single primary key field.")
        pk_value = getattr(self, pk_name, None)
        if pk_value in (None, ""):
            raise ValueError("Cannot update without a primary key value.")

        set_cols = []
        params = []
        index = 1
        for fname, field in self._neutronapi_fields_.items():
            if fname == pk_name:
                continue  # don't update the primary key
            db_col = getattr(field, 'db_column', None) or fname
            val = getattr(self, fname, None)
            if val is None and getattr(field, 'default', None) is not None:
                val = field.default() if callable(field.default) else field.default
            # Convert enum to value
            val = self._convert_enum_value(val)
            if isinstance(val, datetime.datetime) and not is_pg:
                val = val.isoformat()
            # Serialize JSON fields
            if hasattr(field, '__class__') and 'JSONField' in field.__class__.__name__:
                if isinstance(val, (dict, list)):
                    import json
                    val = json.dumps(val)
            placeholder = f"${index}" if is_pg else "?"
            set_cols.append(f"{self._quote(db_col)} = {placeholder}")
            params.append(val)
            index += 1

        # WHERE by primary key
        if is_pg:
            where_placeholder = f"${index}"
        else:
            where_placeholder = "?"
        params.append(pk_value)

        sql = f"UPDATE {table_ident} SET {', '.join(set_cols)} WHERE {self._quote(pk_name)} = {where_placeholder}"
        await db.execute(sql, params if is_pg else tuple(params))
        await db.commit()

    async def delete(self, using: Optional[str] = None):
        """Delete this model instance from the database."""
        alias = using or 'default'
        db = await get_databases().get_connection(alias)
        is_pg = getattr(db, 'db_type', None) == DatabaseType.POSTGRES
        schema, table = self._get_parsed_table_name()
        table_ident = f"{self._quote(schema)}.{self._quote(table)}" if is_pg else self._quote(f"{schema}_{table}")
        
        # Get primary key
        pk_fields = [name for name, f in self._neutronapi_fields_.items() if getattr(f, 'primary_key', False)]
        if len(pk_fields) != 1:
            raise ValueError("Cannot delete without exactly one primary key field.")
        
        pk_name = pk_fields[0]
        pk_value = getattr(self, pk_name, None)
        if pk_value in (None, ""):
            raise ValueError("Cannot delete without a primary key value.")
        
        # Execute DELETE
        placeholder = "$1" if is_pg else "?"
        sql = f"DELETE FROM {table_ident} WHERE {self._quote(pk_name)} = {placeholder}"
        result = await db.execute(sql, [pk_value] if is_pg else (pk_value,))
        await db.commit()
        
        # Clear the primary key to indicate this instance is no longer in the database
        setattr(self, pk_name, None)

    async def refresh_from_db(self, fields=None, using: Optional[str] = None):
        """Reload field values from the database."""
        pk_fields = [name for name, f in self._neutronapi_fields_.items() if getattr(f, 'primary_key', False)]
        if len(pk_fields) != 1:
            raise ValueError("Cannot refresh without exactly one primary key field.")
        
        pk_name = pk_fields[0]
        pk_value = getattr(self, pk_name, None)
        if pk_value in (None, ""):
            raise ValueError("Cannot refresh without a primary key value.")
        
        # Use QuerySet to get fresh data
        qs = QuerySet(self.__class__)
        if using:
            qs = qs.using(using)
        
        try:
            fresh_instance = await qs.get(**{pk_name: pk_value})
        except self.__class__.DoesNotExist:
            raise self.__class__.DoesNotExist(f"{self.__class__.__name__} matching query does not exist.")
        
        # Update only requested fields or all fields
        if fields:
            for field_name in fields:
                if field_name in self._neutronapi_fields_:
                    setattr(self, field_name, getattr(fresh_instance, field_name))
        else:
            for field_name in self._neutronapi_fields_:
                setattr(self, field_name, getattr(fresh_instance, field_name))

    def get_absolute_url(self):
        """Return the absolute URL for this object."""
        raise NotImplementedError(
            f"{self.__class__.__name__} doesn't define a get_absolute_url() method. "
            "You must define this method to use this feature."
        )

    def __str__(self):
        """Return a human-readable representation of the model."""
        pk_fields = [name for name, f in self._neutronapi_fields_.items() if getattr(f, 'primary_key', False)]
        if pk_fields:
            pk_value = getattr(self, pk_fields[0], None)
            return f"{self.__class__.__name__} object ({pk_value})"
        return f"{self.__class__.__name__} object"

    def __repr__(self):
        """Return a detailed representation of the model."""
        return f"<{self.__class__.__name__}: {self.__str__()}>"

    @classproperty  
    def objects(cls):
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
