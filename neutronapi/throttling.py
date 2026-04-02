"""Base throttle contract for NeutronAPI."""
import abc
from typing import Optional


class BaseThrottle(abc.ABC):
    """Abstract throttle that endpoint throttle classes must implement.

    Subclasses own their own configuration (rate, window, backend, etc.).
    The framework calls allow_request(scope) per request — no rate argument.
    """

    @abc.abstractmethod
    async def allow_request(self, scope: dict) -> bool:
        """Return True if the request should be allowed, False to throttle."""
        ...

    async def wait(self) -> Optional[int]:
        """Seconds the client should wait before retrying, or None."""
        return None
