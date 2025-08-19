import datetime
import json
from enum import Enum
from typing import Optional, Any, Union
try:
    import numpy as np  # Optional, used by VectorField
except Exception:  # pragma: no cover
    np = None

from neutronapi import exceptions


class BaseField:
    def __init__(
        self,
        db_column=None,
        null=False,
        default=None,
        max_length=None,
        unique=False,
        blank=False,
        primary_key=False,
    ):
        self._name = None  # Add this to store the field name
        self.db_column = db_column
        self.null = null
        self.blank = blank
        self.default = default
        self.max_length = max_length
        self.value = None
        self.unique = unique
        self.primary_key = primary_key

    def contribute_to_class(self, cls, name):
        """Set the field name when the field is added to a model class"""
        self._name = name
        if self.db_column is None:
            self.db_column = name

    def validate(self, value):
        """Validate the value based on field properties."""
        # Use self._name if available, otherwise fallback to db_column or "unknown field"
        field_name = self._name or self.db_column or "unknown field"

        # First check for null
        if not self.null and value is None:
            raise exceptions.ValidationError(f"Field '{field_name}' cannot be null.")

        # Then check for blank if it's a string-like value
        if isinstance(value, (str, bytes)) and not self.blank and value == "":
            raise exceptions.ValidationError(f"Field '{field_name}' cannot be blank.")

        # Check max_length for string values
        if (
            self.max_length is not None
            and self.max_length is not False
            and isinstance(self.max_length, int)
            and isinstance(value, str)
            and len(value) > self.max_length
        ):
            raise exceptions.ValidationError(
                f"Field '{field_name}' exceeds max_length of {self.max_length}."
            )

    def __repr__(self):
        if self.value is None:
            return ""
        if isinstance(self.value, datetime.datetime):
            return self.value.isoformat()
        if isinstance(self.value, (int, float)):
            return str(self.value)
        return str(self.value)

    def __str__(self):
        if self.value is None:
            return ""
        if isinstance(self.value, datetime.datetime):
            return self.value.isoformat()
        if isinstance(self.value, (int, float)):
            return str(self.value)
        return str(self.value)

    def to_db(self, value=None):
        if isinstance(value, BaseField):
            value = value.value
        return value

    def from_db(self, value):
        self.value = value
        return value

    def describe(self):
        """Return a string representation of the field instance for migrations."""
        attributes = []
        if self.db_column is not None:
            attributes.append(f"db_column='{self.db_column}'")
        if self.null:
            attributes.append("null=True")
        if self.default is not None:
            if callable(self.default):
                default_value = self.default()
            else:
                default_value = self.default
            attributes.append(f"default={default_value}")
        if self.primary_key:
            attributes.append("primary_key=True")
        if self.unique:
            attributes.append("unique=True")
        if self.blank:
            attributes.append("blank=True")
        if self.max_length is not None:
            attributes.append(f"max_length={self.max_length}")

        attr_string = ", ".join(attributes)
        return f"{self.__class__.__name__}({attr_string})"


class DateTimeField(BaseField):
    def __init__(self, db_column=None, null=False, default=None):
        super().__init__(
            db_column=db_column,
            null=null,
            default=default,
        )
        if self.default is not None:
            self.value = self.default() if callable(self.default) else self.default

    def __eq__(self, other):
        if isinstance(other, (DateTimeField, datetime.datetime)):
            if isinstance(other, DateTimeField):
                return self.value == other.value
            return self.value == other
        return False

    def __ne__(self, other):
        if isinstance(other, (DateTimeField, datetime.datetime)):
            if isinstance(other, DateTimeField):
                return self.value != other.value
            return self.value != other
        return True

    def __lt__(self, other):
        if isinstance(other, (DateTimeField, datetime.datetime)):
            if isinstance(other, DateTimeField):
                return self.value < other.value
            return self.value < other
        return False

    def __le__(self, other):
        if isinstance(other, (DateTimeField, datetime.datetime)):
            if isinstance(other, DateTimeField):
                return self.value <= other.value
            return self.value <= other
        return False

    def __gt__(self, other):
        if isinstance(other, (DateTimeField, datetime.datetime)):
            if isinstance(other, DateTimeField):
                return self.value > other.value
            return self.value > other
        return False

    def __ge__(self, other):
        if isinstance(other, (DateTimeField, datetime.datetime)):
            if isinstance(other, DateTimeField):
                return self.value >= other.value
            return self.value >= other
        return False

    def describe(self):
        """Returns a string representation of the field with its parameters"""
        params = []
        if self.null:
            params.append("null=True")
        if self.default is not None:
            if callable(self.default):
                params.append("default=datetime.datetime.now")
            else:
                params.append(f"default={repr(self.default)}")
        if self.db_column is not None:
            params.append(f"db_column='{self.db_column}'")
        if self.unique:
            params.append("unique=True")
        if self.primary_key:
            params.append("primary_key=True")

        return f"DateTimeField({', '.join(params)})"

    def validate(self, value):
        super().validate(value)  # Call base class validation
        if not self.null and value is None:
            raise ValueError("DateTimeField cannot be null.")

        if value is not None:
            if isinstance(value, str):
                try:
                    datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    raise ValueError("Invalid datetime string format")
            elif not isinstance(value, datetime.datetime):
                raise ValueError("Expected a datetime instance or ISO format string")

    def to_db(self, value=None):
        if isinstance(value, BaseField):
            value = value.value
        if value is None:
            if not self.null:
                raise ValueError("DateTimeField cannot be null.")
            return None
        if callable(value):
            value = value()

        # Convert string to datetime if needed
        if isinstance(value, str):
            try:
                value = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Invalid datetime string format")

        if not isinstance(value, datetime.datetime):
            raise ValueError("Expected a datetime instance")

        self.value = value
        # Return the datetime object directly - PostgreSQL needs datetime objects, not strings
        return value

    def from_db(self, value):
        if value is None:
            return None
        if isinstance(value, datetime.datetime):
            return value
        try:
            dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            self.value = dt
            return dt
        except ValueError:
            raise ValueError(f"Invalid datetime format: {value}")

    def get_db_type(self):
        return "TEXT"

    def isoformat(self):
        return self.value.isoformat()


class CharField(BaseField):
    def __init__(
        self,
        max_length=None,
        null=False,
        default=None,
        primary_key=False,
        unique=False,
        blank=False,
        db_column=None,
    ):
        super().__init__(
            db_column=db_column,
            null=null,
            default=default,
            primary_key=primary_key,
            unique=unique,
            blank=blank,
            max_length=max_length,
        )

    def to_db(self, value=None):
        """Convert value to database format without truncation."""
        if isinstance(value, BaseField):
            value = value.value
        if value is None:
            return None
        # Store the full value - let the database handle any truncation
        self.value = str(value)
        return self.value

    def from_db(self, value):
        """Read value from database without modification."""
        if value is None:
            self.value = None
            return None
        self.value = str(value)
        return self.value

    def __str__(self):
        return str(self.value) if self.value is not None else ""

    def __repr__(self):
        return self.__str__()

    # String operations
    def __eq__(self, other):
        if isinstance(other, (CharField, str)):
            return str(self) == str(other)
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __len__(self):
        return len(str(self))

    def __contains__(self, item):
        return item in str(self)

    def __getitem__(self, key):
        return str(self)[key]

    def __add__(self, other):
        return str(self) + str(other)

    def __radd__(self, other):
        return str(other) + str(self)

    # String methods
    def lower(self):
        return str(self).lower()

    def upper(self):
        return str(self).upper()

    def strip(self, chars=None):
        return str(self).strip(chars)

    def lstrip(self, chars=None):
        return str(self).lstrip(chars)

    def rstrip(self, chars=None):
        return str(self).rstrip(chars)

    def split(self, sep=None, maxsplit=-1):
        return str(self).split(sep, maxsplit)

    def rsplit(self, sep=None, maxsplit=-1):
        return str(self).rsplit(sep, maxsplit)

    def replace(self, old, new, count=-1):
        return str(self).replace(old, new, count)

    def startswith(self, prefix, start=None, end=None):
        return str(self).startswith(prefix, start, end)

    def endswith(self, suffix, start=None, end=None):
        return str(self).endswith(suffix, start, end)

    def describe(self):
        """Returns a string representation of the field with its parameters"""
        params = []
        if self.max_length is not None:
            params.append(f"max_length={self.max_length}")
        if self.null:
            params.append("null=True")
        if self.default is not None:
            params.append(f"default={repr(self.default)}")
        if self.primary_key:
            params.append("primary_key=True")
        if self.unique:
            params.append("unique=True")

        return f"CharField({', '.join(params)})"

    def get_db_type(self):
        return f"VARCHAR({self.max_length})"


class TextField(BaseField):
    def __init__(
        self,
        db_column=None,
        null=False,
        default=None,
        unique=False,
        blank=False,
        primary_key=False,
    ):
        super().__init__(
            db_column=db_column,
            null=null,
            blank=blank,
            default=default,
            unique=unique,
            primary_key=primary_key,
            max_length=None,
        )

    def __str__(self):
        return str(self.value) if self.value is not None else ""

    def __repr__(self):
        return repr(self.value) if self.value is not None else ""

    # String operations
    def __eq__(self, other):
        if isinstance(other, (TextField, str)):
            return str(self) == str(other)
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __len__(self):
        return len(str(self))

    def __contains__(self, item):
        return item in str(self)

    def __getitem__(self, key):
        return str(self)[key]

    def __add__(self, other):
        return str(self) + str(other)

    def __radd__(self, other):
        return str(other) + str(self)

    # String methods
    def lower(self):
        return str(self).lower()

    def upper(self):
        return str(self).upper()

    def strip(self, chars=None):
        return str(self).strip(chars)

    def lstrip(self, chars=None):
        return str(self).lstrip(chars)

    def rstrip(self, chars=None):
        return str(self).rstrip(chars)

    def split(self, sep=None, maxsplit=-1):
        return str(self).split(sep, maxsplit)

    def rsplit(self, sep=None, maxsplit=-1):
        return str(self).rsplit(sep, maxsplit)

    def replace(self, old, new, count=-1):
        return str(self).replace(old, new, count)

    def startswith(self, prefix, start=None, end=None):
        return str(self).startswith(prefix, start, end)

    def endswith(self, suffix, start=None, end=None):
        return str(self).endswith(suffix, start, end)

    def describe(self):
        """Returns a string representation of the field with its parameters"""
        params = []
        if self.null:
            params.append("null=True")
        if self.default is not None:
            params.append(f"default={self.default}")
        if self.primary_key:
            params.append("primary_key=True")
        if self.unique:
            params.append("unique=True")
        if self.blank:
            params.append("blank=True")

        return f"TextField({', '.join(params)})"

    def get_db_type(self):
        return "TEXT"


class EnumField(BaseField):
    def __init__(self, enum_class, **kwargs):
        super().__init__(**kwargs)
        self.enum_class = enum_class

    def describe(self):
        """Returns a string representation of the field with its parameters"""
        params = [f"enum_class={self.enum_class.__name__}"]
        if self.null:
            params.append("null=True")
        if self.default is not None:
            params.append(f"default={self.default}")

        return f"EnumField({', '.join(params)})"

    def validate(self, value):
        super().validate(value)  # Call base class validation
        if not self.null and value is None:
            raise exceptions.ValidationError("EnumField cannot be null.")

        if value is not None and not isinstance(value, (self.enum_class, str)):
            raise exceptions.ValidationError(
                f"Value must be a string or {self.enum_class.__name__}"
            )

        if isinstance(value, str):
            try:
                # Try to find matching enum by value
                for member in self.enum_class:
                    if member.value == value:
                        return member
                # If no match found by value, try to create enum from string
                return self.enum_class(value)
            except ValueError:
                raise exceptions.ValidationError(
                    f"Invalid value for {self.enum_class.__name__}: {value}"
                )

    def to_db(self, value=None):
        if isinstance(value, BaseField):
            value = value.value
        if value is None:
            return None
        return value.value if isinstance(value, Enum) else value

    def from_db(self, value):
        if value is None:
            return None
        try:
            # Attempt to convert the database value to an enum member
            return self.enum_class(value)
        except ValueError:
            # Try to find matching enum by value
            for member in self.enum_class:
                if member.value == value:
                    return member
            return None

    def get_db_type(self):
        return "TEXT"


class IntegerField(BaseField):
    def __eq__(self, other):
        if isinstance(other, (IntegerField, int)):
            if isinstance(other, IntegerField):
                return self.value == other.value
            return self.value == other
        return False

    def __ne__(self, other):
        if isinstance(other, (IntegerField, int)):
            if isinstance(other, IntegerField):
                return self.value != other.value
            return self.value != other
        return True

    def __lt__(self, other):
        if isinstance(other, (IntegerField, int)):
            if isinstance(other, IntegerField):
                return self.value < other.value
            return self.value < other
        return False

    def __le__(self, other):
        if isinstance(other, (IntegerField, int)):
            if isinstance(other, IntegerField):
                return self.value <= other.value
            return self.value <= other
        return False

    def __gt__(self, other):
        if isinstance(other, (IntegerField, int)):
            if isinstance(other, IntegerField):
                return self.value > other.value
            return self.value > other
        return False

    def __ge__(self, other):
        if isinstance(other, (IntegerField, int)):
            if isinstance(other, IntegerField):
                return self.value >= other.value
            return self.value >= other
        return False

    def validate(self, value):
        if not self.null and value is None:
            raise ValueError("IntegerField cannot be null.")
        if value is not None:
            try:
                int(value)
            except (TypeError, ValueError):
                raise ValueError("Invalid integer value")

    def to_db(self, value=None):
        if isinstance(value, BaseField):
            value = value.value
        if value is None:
            return None
        return int(value)

    def from_db(self, value):
        if value is None:
            return None
        return int(value)


class BooleanField(BaseField):
    def __init__(
        self,
        db_column=None,
        null=False,
        default=None,
        unique=False,
        blank=False,
        primary_key=False,
        max_length=None,
    ):
        super().__init__(
            db_column=db_column,
            null=null,
            blank=blank,
            default=default,
            unique=unique,
            primary_key=primary_key,
            max_length=max_length,
        )

    def describe(self):
        """Returns a string representation of the field with its parameters"""
        params = []
        if self.null:
            params.append("null=True")
        if self.default is not None:
            params.append(f"default={self.default}")

        return f"BooleanField({', '.join(params)})"

    def validate(self, value):
        if not self.null and value is None:
            raise ValueError("BooleanField cannot be null.")

    def to_db(self, value):
        """Convert boolean to database format, respecting database type differences."""
        if isinstance(value, BaseField):
            value = value.value

        if value is None:
            return None

        # Convert to boolean first (handle "truthy" values)
        bool_value = bool(value)

        # Store the boolean value
        self.value = bool_value

        # For SQLite, integers are used for booleans
        # For PostgreSQL, native boolean values are used
        # Let the database adapter handle the conversion
        return bool_value

    def from_db(self, value):
        """Convert from database format to Python boolean."""
        if value is None:
            return None

        # Whether it's an int (SQLite) or bool (PostgreSQL), convert to Python bool
        return bool(value)

    def get_db_type(self):
        """Return the database column type."""
        return "INTEGER"  # Used by SQLite; PostgreSQL will use BOOLEAN instead


class FloatField(BaseField):
    def __eq__(self, other):
        if isinstance(other, (FloatField, float, int)):
            if isinstance(other, FloatField):
                return self.value == other.value
            return self.value == other
        return False

    def __ne__(self, other):
        if isinstance(other, (FloatField, float, int)):
            if isinstance(other, FloatField):
                return self.value != other.value
            return self.value != other
        return True

    def __lt__(self, other):
        if isinstance(other, (FloatField, float, int)):
            if isinstance(other, FloatField):
                return self.value < other.value
            return self.value < other
        return False

    def __le__(self, other):
        if isinstance(other, (FloatField, float, int)):
            if isinstance(other, FloatField):
                return self.value <= other.value
            return self.value <= other
        return False

    def __gt__(self, other):
        if isinstance(other, (FloatField, float, int)):
            if isinstance(other, FloatField):
                return self.value > other.value
            return self.value > other
        return False

    def __ge__(self, other):
        if isinstance(other, (FloatField, float, int)):
            if isinstance(other, FloatField):
                return self.value >= other.value
            return self.value >= other
        return False

    def validate(self, value):
        if not self.null and value is None:
            raise ValueError("FloatField cannot be null.")
        if value is not None:
            try:
                float(value)
            except (TypeError, ValueError):
                raise ValueError("Invalid float value")

    def to_db(self, value=None):
        if isinstance(value, BaseField):
            value = value.value
        if value is None:
            return None
        return float(value)

    def from_db(self, value):
        if value is None:
            return None
        return float(value)


class JSONField(BaseField):
    def __init__(self, db_column=None, null=False, default=None):
        super().__init__(
            db_column=db_column,
            null=null,
            default=default,
        )

    def to_db(self, value: Union[dict, list] = None) -> Optional[str]:
        """Convert Python object to database JSON format."""
        if value is None:
            return None

        # Handle instances of BaseField
        if isinstance(value, BaseField):
            value = value.value

        # Convert dictionary, list, or callable
        if isinstance(value, (dict, list)):
            self.value = value
            return json.dumps(value)
        elif callable(value):
            self.value = value()
            return json.dumps(self.value)
        else:
            # Try to serialize other types, if possible
            try:
                return json.dumps(value)
            except (TypeError, ValueError):
                raise exceptions.ValidationError(
                    f"Invalid value type for JSONField: {type(value)}"
                )

    def from_db(self, value=None) -> Any:
        """Convert database JSON value to Python object."""
        if value is None:
            return None

        # PostgreSQL drivers often return already-parsed objects
        if isinstance(value, (dict, list)):
            self.value = value
            return value

        # SQLite returns JSON as strings that need to be parsed
        if isinstance(value, str):
            try:
                self.value = json.loads(value)
                return self.value
            except json.JSONDecodeError:
                # If it can't be decoded as JSON, return as is
                self.value = value
                return value

        # Otherwise just return the value
        self.value = value
        return value

    def get(self, param, param1) -> Any:
        return self.value.get(param, param1)

    def __getitem__(self, key) -> Any:
        return self.value[key]

    def __setitem__(self, key, value) -> None:
        self.value[key] = value

    def get_db_type(self):
        # This is used by SQLite
        return "TEXT"

    def describe(self):
        """Returns a string representation of the field with its parameters"""
        params = []
        if self.null:
            params.append("null=True")

        # --- CORRECTED DEFAULT HANDLING ---
        if self.default is not None:
            default_repr = ""
            if self.default is dict:  # Check specifically for the dict class itself
                default_repr = "dict"
            elif self.default is list:  # Check specifically for the list class itself
                default_repr = "list"
            elif callable(self.default):
                # Try to get the name of other callables
                try:
                    default_repr = self.default.__name__
                except AttributeError:
                    # Fallback for callables without a standard name (e.g., complex lambdas)
                    default_repr = repr(self.default)  # Use repr as a fallback
            else:
                # For non-callable default values (e.g., {}, [], None, True) use repr()
                default_repr = repr(self.default)

            params.append(f"default={default_repr}")
        # --- END CORRECTION ---

        if self.db_column is not None:
            params.append(f"db_column='{self.db_column}'")

        return f"JSONField({', '.join(params)})"


class VectorField(BaseField):

    def validate(self, value):
        pass

    def describe(self):
        """Returns a string representation of the field with its parameters"""
        params = []
        if self.null:
            params.append("null=True")
        if self.default is not None:
            params.append(f"default={repr(self.default)}")
        if self.db_column is not None:
            params.append(f"db_column='{self.db_column}'")

        return f"VectorField({', '.join(params)})"

    def to_db(self, value):
        if np is None:
            raise ImportError("numpy is required for VectorField operations")
        if isinstance(value, BaseField):
            value = value.value
        if value is None:
            return None
        if isinstance(value, np.ndarray):
            return value.astype(np.float32).tobytes()
        if isinstance(value, list) and all(isinstance(v, float) for v in value):
            return np.array(value, dtype=np.float32).tobytes()
        raise ValueError(
            "VectorField only accepts numpy arrays or lists of floats as input"
        )

    def from_db(self, value):
        if np is None:
            raise ImportError("numpy is required for VectorField operations")
        return np.frombuffer(value, dtype=np.float32) if value is not None else None

    def get_db_type(self):
        return "BLOB"


class BinaryField(BaseField):
    """Field for storing binary data (BLOB) in the database."""

    def __init__(
        self,
        db_column=None,
        null=False,
        default=None,
        primary_key=False,
        max_length=None,
    ):
        super().__init__(
            db_column=db_column,
            null=null,
            default=default,
            primary_key=primary_key,
        )

    def describe(self):
        """Returns a string representation of the field with its parameters"""
        params = []
        if self.null:
            params.append("null=True")
        if self.default is not None:
            params.append(f"default={repr(self.default)}")
        if self.db_column is not None:
            params.append(f"db_column='{self.db_column}'")

        return f"BinaryField({', '.join(params)})"

    def to_db(self, value):
        if isinstance(value, BaseField):
            value = value.value
        if value is None:
            return None
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        raise ValueError("BinaryField only accepts bytes or str as input")

    def from_db(self, value):
        return value if value is not None else None

    def get_db_type(self):
        return "BLOB"
