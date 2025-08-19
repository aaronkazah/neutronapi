from datetime import datetime
from enum import Enum
from json import JSONEncoder


class CustomJSONEncoder(JSONEncoder):
    """Custom JSON encoder that handles enums and datetimes."""

    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)
