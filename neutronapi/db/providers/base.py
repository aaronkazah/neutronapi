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
    async def create_tables(self):
        pass

    @abstractmethod
    def serialize(self, value: Any) -> str:
        pass

    @abstractmethod
    def deserialize(self, value: str) -> Any:
        pass

