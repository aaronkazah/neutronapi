from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from json import JSONEncoder
from typing import Any

import orjson


def json_default(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class CustomJSONEncoder(JSONEncoder):
    """Custom JSON encoder that handles enums, datetimes, and decimals.

    Extends the standard JSONEncoder to serialize:
    - Enum values to their underlying value
    - datetime objects to ISO format strings
    - Decimal objects to string representation (preserves precision)
    """

    def default(self, obj: Any) -> Any:
        """Convert objects to JSON-serializable format.

        Args:
            obj: Object to serialize

        Returns:
            JSON-serializable representation of the object

        Raises:
            TypeError: If object cannot be serialized
        """
        try:
            return json_default(obj)
        except TypeError:
            return super().default(obj)


def json_dumps_bytes(
    data: Any,
    *,
    indent: int | None = None,
    sort_keys: bool = False,
) -> bytes:
    options = 0
    if sort_keys:
        options |= orjson.OPT_SORT_KEYS
    if indent:
        options |= orjson.OPT_INDENT_2
    return orjson.dumps(data, default=json_default, option=options)


def json_dumps_text(
    data: Any,
    *,
    indent: int | None = None,
    sort_keys: bool = False,
) -> str:
    return json_dumps_bytes(data, indent=indent, sort_keys=sort_keys).decode("utf-8")


def json_loads(data: str | bytes | bytearray | memoryview) -> Any:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return orjson.loads(data)
