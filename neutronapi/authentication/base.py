import abc
from typing import Any, List, Optional


class Authentication(abc.ABC):
    @classmethod
    @abc.abstractmethod
    async def authenticate(cls, email: str, password: str) -> Optional[Any]:
        raise NotImplementedError("Subclasses must implement authenticate")

    @classmethod
    @abc.abstractmethod
    async def authorize(cls, scope: List[str]) -> bool:
        raise NotImplementedError("Subclasses must implement authorize")
