from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any, Tuple


class BaseProvider(ABC):
    """Base database provider interface."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.conn = None

    @abstractmethod
    async def connect(self):
        pass

    @abstractmethod
    async def disconnect(self):
        pass

    @abstractmethod
    async def execute(self, query: str, params: Tuple = ()) -> Any:
        pass

    @abstractmethod
    async def fetchone(self, query: str, params: Tuple = ()) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def fetchall(self, query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def get_placeholder(self, index: int = 1) -> str:
        """Get parameter placeholder for this database dialect."""
        pass
    
    @abstractmethod
    def get_placeholders(self, count: int) -> str:
        """Get multiple parameter placeholders for this database dialect."""
        pass

    @abstractmethod
    async def create_tables(self):
        pass

    @abstractmethod
    def serialize(self, value: Any) -> str:
        pass

    @abstractmethod
    def deserialize(self, value: str) -> Any:
        pass

    # Optional hook: providers can implement automatic full-text setup during migrations
    async def setup_full_text(self, app_label: str, table_base_name: str, search_meta: dict, fields: Dict[str, Any]):
        """Create database-specific full-text search structures.

        Default implementation does nothing. Providers may override.
        """
        return
