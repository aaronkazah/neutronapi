import bcrypt
import asyncio
from typing import Any, List, Optional
import abc


class Authentication(abc.ABC):
    @classmethod
    @abc.abstractmethod
    async def authenticate(cls, email: str, password: str) -> Optional[Any]:
        raise NotImplementedError("Subclasses must implement authenticate")

    @classmethod
    @abc.abstractmethod
    async def authorize(cls, scope: List[str]) -> bool:
        raise NotImplementedError("Subclasses must implement authorize")

    @staticmethod
    async def hash_password(password: str) -> str:
        def _hash():
            salt = bcrypt.gensalt()
            hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
            return hashed.decode("utf-8")

        return await asyncio.to_thread(_hash)

    @staticmethod
    async def check_password(hashed_password: str, plain_password: str) -> bool:
        def _check():
            return bcrypt.checkpw(
                plain_password.encode("utf-8"), hashed_password.encode("utf-8")
            )

        return await asyncio.to_thread(_check)
