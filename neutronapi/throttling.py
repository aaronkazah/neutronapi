"""Throttle contract and built-in implementations for NeutronAPI."""
import abc
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


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

    async def get_headers(self) -> dict[str, str]:
        """Return quota headers for the current request."""
        return {}


class SlidingWindowThrottle(BaseThrottle):
    """In-memory sliding window rate limiter.

    Tracks request timestamps per key (IP or user) and rejects requests
    that exceed the configured rate within the window.

    Usage:
        class LoginThrottle(SlidingWindowThrottle):
            rate = "10/minute"      # 10 requests per 60 seconds
            scope_attr = "ip"       # throttle by IP (or "user" for authenticated)

        @API.endpoint("/login", methods=["POST"], throttle_classes=[LoginThrottle])
        async def login(self, scope, receive, send, **kwargs):
            ...
    """

    rate: str = "60/minute"  # "N/second", "N/minute", "N/hour", "N/day"
    scope_attr: str = "ip"   # "ip" or "user"

    # Shared in-memory store — per class, not per instance
    _histories: Dict[str, List[float]] = defaultdict(list)

    DURATION_MAP = {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
    }

    def __init__(self):
        self._num_requests, self._duration = self._parse_rate(self.rate)
        self._wait_seconds: Optional[int] = None

    @classmethod
    def _parse_rate(cls, rate: str) -> Tuple[int, int]:
        """Parse rate string like '10/minute' into (num_requests, duration_seconds)."""
        num, period = rate.split("/")
        num_requests = int(num)
        duration = cls.DURATION_MAP.get(period)
        if duration is None:
            raise ValueError(
                f"Invalid rate period '{period}'. "
                f"Must be one of: {', '.join(cls.DURATION_MAP.keys())}"
            )
        return num_requests, duration

    def _get_key(self, scope: dict) -> str:
        """Extract the throttle key from the request scope."""
        if self.scope_attr == "user":
            user = scope.get("user")
            if isinstance(user, dict):
                return user.get("id") or user.get("email") or "anonymous"
            return str(user) if user else "anonymous"
        # Default: throttle by IP
        client = scope.get("client") or ("unknown", 0)
        return client[0]

    async def allow_request(self, scope: dict) -> bool:
        key = f"{self.__class__.__name__}:{self._get_key(scope)}"
        now = time.monotonic()
        cutoff = now - self._duration

        # Prune expired entries
        history = self._histories[key]
        self._histories[key] = [t for t in history if t > cutoff]
        history = self._histories[key]

        if len(history) >= self._num_requests:
            # Calculate wait time until the oldest request in window expires
            self._wait_seconds = int(history[0] - cutoff) + 1
            return False

        history.append(now)
        self._wait_seconds = None
        return True

    async def wait(self) -> Optional[int]:
        return self._wait_seconds

    async def get_headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self._num_requests),
            "X-RateLimit-Window": str(self._duration),
        }
