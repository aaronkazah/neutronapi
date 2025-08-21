import datetime
try:
    import numpy as np  # optional
except Exception:  # pragma: no cover
    np = None
import os
import re
from typing import Optional, Dict, List, Any, Union


class Q:
    """A Q object represents a complex query that can be combined with logical operators."""

    AND = "AND"
    OR = "OR"

    def __init__(self, **kwargs):
        self.children = list(kwargs.items())
        self.connector = self.AND
        self.negated = False

    def _combine(self, other, conn):
        if not isinstance(other, Q):
            raise TypeError(f"Cannot combine Q object with {type(other)}")

        obj = Q()
        obj.connector = conn
        obj.children = [self, other]
        return obj

    def __and__(self, other):
        return self._combine(other, self.AND)

    def __or__(self, other):
        return self._combine(other, self.OR)

    def __invert__(self):
        obj = Q()
        obj.negated = not self.negated
        obj.children = [self]
        return obj


class Object:
    """
    A dictionary-like object that allows attribute access to its keys,
    and provides methods to interact with the database.
    """

    def __init__(self, data: Dict[str, Any], queryset: 'QuerySet'):
        super().__setattr__('_data', data)
        super().__setattr__('_queryset', queryset)

    def __getattr__(self, name: str) -> Any:
        try:
            value = self._data[name]
            # Handle timestamp fields automatically
            if name in ['created', 'modified'] and value is not None:
                if isinstance(value, str):
                    try:
                        import datetime
                        return datetime.datetime.fromisoformat(value)
                    except (ValueError, TypeError):
                        # If conversion fails, return as-is
                        return value
            return value
        except KeyError:
            raise AttributeError(f"'Object' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any):
        if name.startswith('_'):
            super().__setattr__(name, value)
        else:
            self._data[name] = value

    def __setitem__(self, key: str, value: Any):
        self._data[key] = value

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __repr__(self) -> str:
        key = self._data.get('key') or self._data.get('id')
        return f"<Object: {key}>"

    async def save(self):
        # Validate before saving
        await self.validate()
        
        # Set timestamps
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        if not self._data.get('created'):
            self._data['created'] = now
        self._data['modified'] = now
        
        if 'id' not in self._data:
            raise ValueError("Cannot save object without an 'id'")

        updates = self._data.copy()
        obj_id = updates.pop('id')
        updates.pop('created', None)

        await self._queryset.filter(id=obj_id).update(**updates)
        updated_obj = await self._queryset.filter(id=obj_id).first()
        if updated_obj:
            super().__setattr__('_data', updated_obj._data)

    async def delete(self):
        # Prefer model primary key; do not assume arbitrary key fields
        key_field = None
        model = getattr(self._queryset, 'model', None)
        if model is not None and hasattr(model, '_fields'):
            try:
                pk_fields = [name for name, f in model._fields.items() if getattr(f, 'primary_key', False)]
                if len(pk_fields) == 1:
                    key_field = pk_fields[0]
            except Exception:
                pass
        if not key_field:
            raise ValueError("Cannot delete without a primary key; construct QuerySet with a model that defines one.")
        if key_field not in self._data:
            raise ValueError(f"Cannot delete object without a '{key_field}' value")
        await self._queryset.filter(**{key_field: self._data[key_field]}).delete()

    async def refresh_from_db(self):
        # Prefer model primary key; do not assume arbitrary key fields
        key_field = None
        model = getattr(self._queryset, 'model', None)
        if model is not None and hasattr(model, '_fields'):
            try:
                pk_fields = [name for name, f in model._fields.items() if getattr(f, 'primary_key', False)]
                if len(pk_fields) == 1:
                    key_field = pk_fields[0]
            except Exception:
                pass
        if not key_field:
            raise ValueError("Cannot refresh without a primary key; construct QuerySet with a model that defines one.")
        if key_field not in self._data:
            raise ValueError(f"Cannot refresh object without a '{key_field}' value")

        updated_obj = await self._queryset.filter(**{key_field: self._data[key_field]}).first()
        if updated_obj:
            super().__setattr__('_data', updated_obj._data)

    def _validate_key(self) -> None:
        """Validate key field following organizational structure."""
        k = self._data.get('key')

        if not k or len(k) > 1024:
            raise ValueError("key required and ≤1024 chars")

        # All paths must be file paths and cannot end with a slash
        if k.endswith("/"):
            raise ValueError("key must not end with '/'")

        if not k.startswith("/"):
            raise ValueError("key must start with '/'")

        # Allow URL-encoded characters (% followed by hex digits) in addition to the original allowed characters
        if not re.match(r"^[a-zA-Z0-9/!_.*'()\-%]+$", k):
            raise ValueError(
                f"path contains invalid characters: '{k}' - only alphanumeric, /, !, _, ., *, ', (, ), -, and % are allowed"
            )

        # Validate organizational structure: first path segment must start with acc- or org-
        path_parts = k.strip("/").split("/")
        if len(path_parts) > 0 and path_parts[0]:
            first_segment = path_parts[0]
            if not (
                first_segment.startswith("acc-") or first_segment.startswith("org-")
            ):
                raise ValueError(
                    f"key must begin with either 'acc-' or 'org-' after the root slash. Got: '{first_segment}'"
                )

    def _validate_name(self) -> None:
        """Validate name field - can be null but if provided cannot be empty."""
        name = self._data.get('name')
        if name is not None and not name.strip():
            raise ValueError("name cannot be empty if provided")

    def _validate_connections(self) -> None:
        """Validate connections field - must be a dict with object IDs as keys and dict attrs as values."""
        connections = self._data.get('connections')
        if connections is None:
            return

        if not isinstance(connections, dict):
            raise ValueError("connections must be a dictionary")

        for connection_id, attrs in connections.items():
            # Validate connection ID format
            if not isinstance(connection_id, str):
                raise ValueError("connection ID must be a string")

            # Validate ID format (should be obj-xxx format)
            if not connection_id.startswith("obj-"):
                raise ValueError(
                    f"connection ID must start with 'obj-': {connection_id}"
                )

            # Validate attributes
            if not isinstance(attrs, dict):
                raise ValueError(
                    f"connection attributes must be a dictionary for ID: {connection_id}"
                )

    def get_display_name(self) -> str:
        """Get display name - returns name if set, otherwise filename from key."""
        name = self._data.get('name')
        if name:
            return name

        # Extract filename from key
        key = self._data.get('key')
        if key:
            filename = os.path.basename(key)
            # Remove extension if present
            if "." in filename:
                return filename.rsplit(".", 1)[0]
            return filename

        return ""

    def populate(self, key: str) -> None:
        """Populate folder, parent, and organization fields from the given key path.

        Args:
            key: The file path key (e.g., '/acc1/element.py')

        Example:
            For key '/acc1/element.py':
            - folder becomes '/acc1'
            - parent becomes '/' # parent directory of the folder not file
        """
        self._data['key'] = key

        # Extract folder (directory containing the file)
        folder_path = os.path.dirname(key)
        self._data['folder'] = folder_path if folder_path != "/" else "/"

        # Extract parent (parent directory of the folder)
        if folder_path == "/":
            # Root folder has no parent
            self._data['parent'] = None
        else:
            parent_path = os.path.dirname(folder_path)
            self._data['parent'] = parent_path if parent_path != "/" else "/"

    async def validate(self):
        """Validate the object before saving."""
        self._validate_key()
        self._validate_name()
        self._validate_connections()
        key = self._data.get('key')
        if key:
            self.populate(key)

    # In class Object:
    def serialize(self) -> Dict[str, Any]:
        """
        Returns the object's data as a JSON-serializable dictionary.
        Datetimes are converted to ISO 8601 strings.
        """
        serialized_data = {}
        
        # Handle case where _data might not be a dict or items() returns unexpected format
        if not hasattr(self._data, 'items') or not callable(self._data.items):
            return serialized_data
            
        try:
            for key, value in self._data.items():
                if isinstance(value, datetime.datetime):
                    serialized_data[key] = value.isoformat()
                elif isinstance(value, np.ndarray):
                    # Example for handling numpy arrays if they exist
                    serialized_data[key] = value.tolist()
                else:
                    serialized_data[key] = value
        except (ValueError, TypeError):
            # If unpacking fails, try to handle the data differently
            if isinstance(self._data, dict):
                serialized_data = dict(self._data)
            else:
                serialized_data = {"error": "Unable to serialize data"}
                
        return serialized_data


class QuerySet:
    """QuerySet for database operations with chaining support.

    Note: This class can target any table. Pass the table name explicitly and
    optionally provide the set of JSON-capable columns. Defaults avoid
    hardcoding model-specific fields.
    """

    _json_fields = set()

    def __init__(self, model_cls):
        # Simple constructor that takes a Model class, like the old working code
        self.model = model_cls
        self.table = model_cls.get_table_name()
        self._model_class = model_cls
        
        # Database access is deferred until needed
        self.db = None
        self.provider = None
        self._filters = []
        self._order_by = []
        self._limit_count = None
        self._offset_count = None
        self._select_fields = ["*"]
        self._values_mode = False
        self._values_fields = []
        self._values_flat = False
        self._result_cache = None
        
        # Will be determined when we get the provider
        self._is_sqlite = None
        
        # Derive JSON fields from the model
        derived_json = set()
        if hasattr(model_cls, '_fields'):
            try:
                from .fields import JSONField
                for fname, f in model_cls._fields.items():
                    if isinstance(f, JSONField):
                        derived_json.add(fname)
            except Exception:
                pass
        self._json_fields = derived_json
    
    async def _get_provider(self):
        """Get and cache the database provider, and initialize dialect flags."""
        if hasattr(self, '_model_class'):
            from .connection import get_databases
            db_manager = get_databases()
            connection = await db_manager.get_connection()
            provider = connection.provider
            # Cache provider for subsequent non-query-building paths (update/delete)
            self.provider = provider
            # Initialize dialect flag before any SQL construction
            if self._is_sqlite is None:
                self._is_sqlite = 'sqlite' in provider.__class__.__name__.lower()
            return provider
        else:
            # If provider already set externally, ensure dialect flag is set
            if self.provider and self._is_sqlite is None:
                self._is_sqlite = 'sqlite' in self.provider.__class__.__name__.lower()
            return self.provider

    def filter(self, *args, **kwargs) -> 'QuerySet':
        return self._add_filters(args, kwargs, negated=False)

    def exclude(self, *args, **kwargs) -> 'QuerySet':
        return self._add_filters(args, kwargs, negated=True)

    def _add_filters(self, args, kwargs, negated=False):
        qs = self._clone()
        q_objects = list(args)

        if kwargs:
            q_objects.append(Q(**kwargs))

        if not q_objects:
            return qs

        if negated:
            # Negate each Q object before combining
            q_objects = [~q for q in q_objects]

        # Add new filters to the list
        for q_obj in q_objects:
            qs._filters.append({'type': 'q_object', 'q_object': q_obj})
        return qs

    def order_by(self, *fields) -> 'QuerySet':
        qs = self._clone()
        qs._order_by = []
        for field in fields:
            if field.startswith('-'):
                qs._order_by.append(f"{field[1:]} DESC")
            else:
                qs._order_by.append(f"{field} ASC")
        return qs

    def limit(self, count: int) -> 'QuerySet':
        qs = self._clone()
        qs._limit_count = count
        return qs

    def offset(self, count: int) -> 'QuerySet':
        qs = self._clone()
        qs._offset_count = count
        return qs

    def values(self, *fields) -> 'QuerySet':
        qs = self._clone()
        qs._select_fields = list(fields) if fields else ["*"]
        qs._values_mode = True
        qs._values_fields = list(fields)
        return qs

    def values_list(self, *fields, flat=False) -> 'QuerySet':
        if flat and len(fields) != 1:
            raise ValueError("values_list() with flat=True can only be used with a single field")

        qs = self.values(*fields)
        qs._values_flat = flat
        return qs

    def distinct(self, field: str = None) -> 'QuerySet':
        qs = self._clone()
        if field:
            qs._select_fields = [f"DISTINCT {field}"]
        else:
            qs._select_fields = ["DISTINCT *"]
        return qs

    def all(self):
        """Return the queryset itself (unevaluated), Django-style."""
        return self._clone()

    async def _fetch_all(self) -> List[Union['Object', Dict, Any]]:
        # Ensure provider/dialect is initialized before constructing SQL
        provider = await self._get_provider()
        sql, params = self._build_query()
        results = await provider.fetchall(sql, tuple(params))

        if not self._values_mode:
            return [self._deserialize_result(result) for result in results if result]

        processed_results = []
        for row in results:
            row_dict = dict(row)
            if not self._values_fields:
                processed_results.append(row_dict)
                continue

            if self._values_flat:
                processed_results.append(row_dict.get(self._values_fields[0]))
            else:
                if len(self._values_fields) == 1:
                    processed_results.append((row_dict.get(self._values_fields[0]),))
                else:
                    processed_results.append(tuple(row_dict.get(f) for f in self._values_fields))
        return processed_results

    async def first(self) -> Optional[Union['Object', Dict, Any]]:
        qs = self.limit(1)
        results = await qs._fetch_all()
        return results[0] if results else None

    async def last(self) -> Optional['Object']:
        if self._values_mode:
            raise TypeError("Cannot call last() after values() or values_list()")

        if not self._order_by:
            # Default to model primary key when available; else 'id'
            order_field = None
            if self.model is not None and hasattr(self.model, '_fields'):
                try:
                    pk_fields = [name for name, f in self.model._fields.items() if getattr(f, 'primary_key', False)]
                    if len(pk_fields) == 1:
                        order_field = pk_fields[0]
                except Exception:
                    pass
            if not order_field:
                order_field = 'id'
            qs = self.order_by(f'-{order_field}').limit(1)
        else:
            reversed_order = []
            for order in self._order_by:
                if order.endswith(' DESC'):
                    reversed_order.append(order.replace(' DESC', ' ASC'))
                else:
                    reversed_order.append(order.replace(' ASC', ' DESC'))
            qs = self._clone()
            qs._order_by = reversed_order
            qs = qs.limit(1)

        results = await qs._fetch_all()
        return results[0] if results else None

    async def count(self) -> int:
        qs = self._clone()
        qs._select_fields = ["COUNT(*)"]
        qs._order_by = []
        qs._limit_count = None
        qs._offset_count = None

        # Ensure provider/dialect is initialized before constructing SQL
        provider = await self._get_provider()
        sql, params = qs._build_query()
        result = await provider.fetchone(sql, tuple(params))

        if result:
            return list(result.values())[0] if isinstance(result, dict) else result[0]
        return 0

    async def exists(self) -> bool:
        qs = self.values('key').limit(1)
        result = await qs.first()
        return result is not None

    def __len__(self):
        if self._result_cache is None:
            raise TypeError("Cannot determine length of unevaluated queryset. Use 'await' first.")
        return len(self._result_cache)

    def __iter__(self):
        if self._result_cache is None:
            raise TypeError("Cannot iterate over an unevaluated queryset. Use 'await' first.")
        return iter(self._result_cache)

    def __await__(self):
        async def _populate_and_return_self():
            if self._result_cache is None:
                self._result_cache = await self._fetch_all()
            return self
        return _populate_and_return_self().__await__()

    async def __aiter__(self):
        if self._result_cache is None:
            self._result_cache = await self._fetch_all()
        results = self._result_cache
        for item in results:
            yield item

    async def get(self, *args, **kwargs) -> 'Object':
        if self._values_mode:
            raise TypeError("Cannot call get() after values() or values_list()")

        qs = self.filter(*args, **kwargs)
        results = await qs.limit(2)._fetch_all()

        if not results:
            raise self._model_class.DoesNotExist(f"{self._model_class.__name__} matching query does not exist.")
        elif len(results) > 1:
            raise MultipleObjectsReturned(f"get() returned more than one {self._model_class.__name__} -- it returned {len(results)}!")

        return results[0]

    async def get_or_none(self, *args, **kwargs) -> Optional['Object']:
        try:
            return await self.get(*args, **kwargs)
        except (self._model_class.DoesNotExist, MultipleObjectsReturned):
            return None

    async def vector_search(self, query_vector, top_k: int = 10, **pre_filters):
        from .vector_search import VectorSearch
        vs = VectorSearch(self)
        return await vs.vector_search(query_vector, top_k, **pre_filters)

    async def delete(self) -> int:
        # Ensure provider/dialect is initialized before constructing SQL
        provider = await self._get_provider()
        where_clause, params = self._build_where_clause()

        if not where_clause:
            # Allow deleting all objects if no filters are provided
            sql = f"DELETE FROM {self.table}"
            params = []
        else:
            sql = f"DELETE FROM {self.table} WHERE {where_clause}"

        await provider.execute(sql, tuple(params))
        return 1

    async def create(self, **kwargs):
        """Create a new record in the database by instantiating and saving the model."""
        # Convert any Enum values
        converted_kwargs = self._convert_enum_values(kwargs)
        instance = self._model_class(**converted_kwargs)
        await instance.save(create=True)
        return instance


    async def update(self, **kwargs) -> int:
        if not kwargs:
            return 0

        kwargs['modified'] = datetime.datetime.now(tz=datetime.timezone.utc)

        # Ensure provider/dialect is initialized before constructing SQL
        provider = await self._get_provider()

        set_clauses = []
        set_params = []
        param_counter = 1

        for field, value in kwargs.items():
            if field in self._json_fields:
                value = self.provider.serialize(value)

            # *** FIX: Use correct placeholder based on dialect ***
            placeholder = '?' if self._is_sqlite else f'${param_counter}'
            set_clauses.append(f"{field} = {placeholder}")
            set_params.append(value)
            param_counter += 1

        where_clause, where_params = self._build_where_clause(param_counter)

        if not where_clause:
            raise ValueError("Cannot update all objects without filters.")

        sql = f"UPDATE {self.table} SET {', '.join(set_clauses)} WHERE {where_clause}"
        params = set_params + where_params

        await provider.execute(sql, tuple(params))
        return 1

    def _convert_enum_values(self, data: dict) -> dict:
        """Convert any Enum values in a dict to their string values."""
        converted = {}
        for key, value in data.items():
            if hasattr(value, 'value'):  # Enum-like object
                converted[key] = value.value
            else:
                converted[key] = value
        return converted

    def _clone(self) -> 'QuerySet':
        qs = QuerySet(self._model_class)
        qs._filters = self._filters.copy()
        qs._order_by = self._order_by.copy()
        qs._limit_count = self._limit_count
        qs._offset_count = self._offset_count
        qs._select_fields = self._select_fields.copy()
        qs._values_mode = self._values_mode
        qs._values_fields = self._values_fields.copy()
        qs._values_flat = self._values_flat
        return qs

    def _build_where_clause(self, param_start: int = 1) -> tuple:
        if not self._filters:
            return "", []

        all_conditions = []
        all_params = []
        param_counter = param_start

        for filter_item in self._filters:
            if filter_item.get('type') == 'q_object':
                q_condition, q_params = self._build_q_condition(filter_item['q_object'], param_counter)
                if q_condition:
                    all_conditions.append(f"({q_condition})")
                    all_params.extend(q_params)
                    param_counter += len(q_params)

        if not all_conditions:
            return "", []

        return " AND ".join(all_conditions), all_params

    def _build_q_condition(self, q_obj: 'Q', param_start: int) -> tuple:
        """Recursively build SQL condition and parameters from a Q object."""
        parts = []
        params = []
        param_counter = param_start

        # Handle case where all children are Q objects (combined Q objects)
        if all(isinstance(child, Q) for child in q_obj.children):
            for child_q in q_obj.children:
                condition, q_params = self._build_q_condition(child_q, param_counter)
                if condition:
                    parts.append(f"({condition})")
                    params.extend(q_params)
                    param_counter += len(q_params)
        else:
            # Handle mixed children (tuples and Q objects)
            for child in q_obj.children:
                if isinstance(child, Q):
                    condition, q_params = self._build_q_condition(child, param_counter)
                    if condition:
                        parts.append(f"({condition})")
                        params.extend(q_params)
                        param_counter += len(q_params)
                elif isinstance(child, tuple) and len(child) == 2:
                    field, value = child
                    lookup_parts = field.split('__')
                    field_name = lookup_parts[0]
                    
                    # Handle JSON fields differently - they may have nested paths
                    if field_name in self._json_fields:
                        # For JSON fields, check if the last part is a lookup type
                        potential_lookup = lookup_parts[-1] if len(lookup_parts) > 1 else 'exact'
                        valid_lookups = {'exact', 'iexact', 'contains', 'icontains', 'startswith', 'endswith', 'gt', 'gte', 'lt', 'lte', 'in', 'isnull'}
                        
                        if potential_lookup in valid_lookups:
                            lookup_type = potential_lookup
                            path = lookup_parts[1:-1]  # Everything between field_name and lookup_type
                        else:
                            lookup_type = 'exact'
                            path = lookup_parts[1:]    # Everything after field_name
                        
                        # Process as JSON field
                        json_filter = {'field': field_name, 'path': path, 'lookup': lookup_type, 'value': value}
                        condition, json_params = self._build_json_condition(json_filter, param_counter)
                        if condition:
                            parts.append(condition)
                            params.extend(json_params)
                            param_counter += len(json_params)
                        continue
                    else:
                        # Regular field
                        lookup_type = 'exact' if len(lookup_parts) == 1 else lookup_parts[-1]

                    # *** FIX: Simplified map, placeholder logic is now separate ***
                    lookup_map = {
                        'exact': '=', 'iexact': '=', 'contains': 'LIKE', 'icontains': 'ILIKE',
                        'startswith': 'LIKE', 'endswith': 'LIKE', 'gt': '>', 'gte': '>=',
                        'lt': '<', 'lte': '<=', 'in': 'IN', 'isnull': 'IS NULL'
                    }

                    # For SQLite, ILIKE is not standard, use LIKE with LOWER()
                    if self._is_sqlite and lookup_type == 'icontains':
                        lookup_type = 'contains'  # Will be handled by LOWER() later

                    if lookup_type not in lookup_map and field_name not in self._json_fields:
                        raise ValueError(f"Unsupported lookup type: {lookup_type}")

                    if field_name in self._json_fields:
                        json_path = lookup_parts[1:-1] if lookup_type in lookup_map else lookup_parts[1:]
                        json_filter = {'field': field_name, 'path': json_path, 'lookup': lookup_type, 'value': value}

                        condition, json_params = self._build_json_condition(json_filter, param_counter)
                        if condition:
                            parts.append(condition)
                            params.extend(json_params)
                            param_counter += len(json_params)
                    else:
                        if lookup_type == 'in':
                            if not hasattr(value, '__iter__') or isinstance(value, str):
                                raise ValueError(f"Value for 'in' lookup must be an iterable. Got {type(value)}")
                            if not value:
                                parts.append("1=0")
                            else:
                                # *** FIX: Generate correct placeholders for IN clause ***
                                if self._is_sqlite:
                                    placeholders = ', '.join(['?'] * len(value))
                                else:
                                    placeholders = ', '.join(
                                        [f'${i}' for i in range(param_counter, param_counter + len(value))])

                                condition = f"{field_name} IN ({placeholders})"
                                parts.append(condition)
                                params.extend(value)
                                param_counter += len(value)
                        elif lookup_type == 'isnull':
                            condition = f"{field_name} IS NULL" if value else f"{field_name} IS NOT NULL"
                            parts.append(condition)
                        else:
                            # *** FIX: Centralized placeholder and condition generation ***
                            op = lookup_map[lookup_type]
                            placeholder = '?' if self._is_sqlite else f'${param_counter}'

                            # Handle case-insensitivity for SQLite
                            field_expr = field_name
                            value_expr = placeholder
                            if self._is_sqlite and lookup_type in ['iexact', 'icontains']:
                                field_expr = f"LOWER({field_name})"
                                value_expr = f"LOWER({placeholder})"

                            condition = f"{field_expr} {op} {value_expr}"
                            parts.append(condition)

                            if lookup_type in ['contains', 'icontains']:
                                params.append(f"%{value}%")
                            elif lookup_type == 'startswith':
                                params.append(f"{value}%")
                            elif lookup_type == 'endswith':
                                params.append(f"%{value}")
                            else:
                                params.append(value)
                            param_counter += 1
                else:
                    raise ValueError(f"Invalid Q object child: {child}")

        condition_str = f" {q_obj.connector} ".join(parts)
        if q_obj.negated and condition_str:
            condition_str = f"NOT ({condition_str})"

        return condition_str, params

    def _build_json_condition(self, filter_item: dict, param_start: int) -> tuple:
        field, path, lookup, value = filter_item['field'], filter_item['path'], filter_item['lookup'], filter_item[
            'value']

        params = []
        condition = ""
        # *** FIX: Use correct placeholder based on dialect ***
        placeholder = '?' if self._is_sqlite else f'${param_start}'

        if self._is_sqlite:
            json_path_str = f"$.{'.'.join(path)}" if path else "$"
            json_expr = f"json_extract({field}, '{json_path_str}')"

            if lookup == 'isnull':
                condition = f"{json_expr} IS {'NULL' if value else 'NOT NULL'}"
            else:
                op_map = {'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<='}
                if lookup == 'exact':
                    condition = f"CAST({json_expr} AS TEXT) = {placeholder}"
                    params.append(str(value))
                elif lookup == 'contains':
                    condition = f"CAST({json_expr} AS TEXT) LIKE {placeholder}"
                    params.append(f"%{value}%")
                elif lookup == 'icontains':
                    condition = f"LOWER(CAST({json_expr} AS TEXT)) LIKE LOWER({placeholder})"
                    params.append(f"%{value}%")
                elif lookup in op_map:
                    op = op_map[lookup]
                    cast_type = "NUMERIC" if isinstance(value, (int, float)) else "TEXT"
                    condition = f"CAST({json_expr} AS {cast_type}) {op} {placeholder}"
                    params.append(str(value) if isinstance(value, (int, float)) else value)
        else:  # PostgreSQL JSONB
            if path:
                # Build proper PostgreSQL JSON path with literal keys
                if len(path) == 1:
                    # Single key: field->>'key'
                    text_path_expr = f"{field}->>'{path[0]}'"
                    path_expr = f"{field}->'{path[0]}'"
                else:
                    # Multiple keys: field->'key1'->'key2'->>'finalkey'
                    json_path_parts = "->".join(f"'{key}'" for key in path[:-1])
                    text_path_expr = f"{field}->{json_path_parts}->>'{path[-1]}'"
                    path_expr = f"{field}->{json_path_parts}->'{path[-1]}'"
            else:
                # No path, just the field itself
                path_expr = field
                text_path_expr = f"{field}::text"

            if lookup == 'isnull':
                condition = f"{path_expr} IS {'NULL' if value else 'NOT NULL'}"
            elif lookup == 'exact':
                # Force parameter to text to avoid JSON type inference issues
                condition = f"{text_path_expr} = {placeholder}::text"
                params.append(str(value))
            elif lookup == 'contains':
                condition = f"{text_path_expr} LIKE {placeholder}::text"
                params.append(f"%{value}%")
            elif lookup == 'startswith':
                condition = f"{text_path_expr} LIKE {placeholder}::text"
                params.append(f"{value}%")
            elif lookup == 'endswith':
                condition = f"{text_path_expr} LIKE {placeholder}::text"
                params.append(f"%{value}")
            elif lookup == 'icontains':
                condition = f"LOWER({text_path_expr}) LIKE LOWER({placeholder}::text)"
                params.append(f"%{value}%")
            else:
                # Handle comparison operators (gt, gte, lt, lte)
                op_map = {'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<='}
                if lookup in op_map:
                    op = op_map[lookup]
                    # Cast JSON text to appropriate type for comparison
                    if isinstance(value, (int, float)):
                        condition = f"CAST({text_path_expr} AS NUMERIC) {op} {placeholder}"
                        params.append(str(value))  # Convert to string for PostgreSQL
                    else:
                        condition = f"{text_path_expr} {op} {placeholder}::text"
                        params.append(str(value))

        return condition, params

    def _build_query(self) -> tuple:
        select_clause = ", ".join(self._select_fields)
        sql = f"SELECT {select_clause} FROM {self.table}"

        where_clause, params = self._build_where_clause()
        if where_clause:
            sql += f" WHERE {where_clause}"

        if self._order_by:
            sql += f" ORDER BY {', '.join(self._order_by)}"

        if self._limit_count is not None:
            sql += f" LIMIT {self._limit_count}"

        if self._offset_count is not None:
            sql += f" OFFSET {self._offset_count}"

        return sql, params

    def _deserialize_result(self, result: Dict[str, Any]) -> Optional['Object']:
        if not result:
            return None

        result_dict = dict(result)

        if hasattr(self.provider, 'deserialize'):
            for field in self._json_fields:
                if result_dict.get(field) and isinstance(result_dict[field], str):
                    result_dict[field] = self.provider.deserialize(result_dict[field])

        for field, value in result_dict.items():
            if isinstance(value, datetime.datetime):
                result_dict[field] = value.isoformat()

        for field in self._json_fields:
            result_dict.setdefault(field, {})
        result_dict.setdefault("size", 0)

        return Object(result_dict, self)




class MultipleObjectsReturned(Exception):
    pass
