from datetime import datetime
from enum import Enum
from json import JSONEncoder
from typing import Any


class CustomJSONEncoder(JSONEncoder):
    """Custom JSON encoder that handles enums and datetimes.
    
    Extends the standard JSONEncoder to serialize:
    - Enum values to their underlying value
    - datetime objects to ISO format strings
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
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)
