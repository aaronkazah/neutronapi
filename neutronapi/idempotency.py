"""Idempotency support for mutating HTTP requests."""

from __future__ import annotations

import abc
import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from neutronapi.base import Response


@dataclass(frozen=True)
class CachedResponse:
    status: int
    headers: list[tuple[bytes, bytes]]
    body: bytes


class IdempotencyStore(abc.ABC):
    @abc.abstractmethod
    async def get(self, key: str) -> Optional[CachedResponse]:
        raise NotImplementedError

    @abc.abstractmethod
    async def reserve(self, key: str, ttl: int) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    async def complete(self, key: str, response: CachedResponse, ttl: int) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def release(self, key: str) -> None:
        raise NotImplementedError


@dataclass
class _StoredEntry:
    state: str
    expires_at: float
    response: Optional[CachedResponse] = None


class InMemoryIdempotencyStore(IdempotencyStore):
    """In-memory idempotency store with TTL expiry."""

    def __init__(self) -> None:
        self._entries: dict[str, _StoredEntry] = {}
        self._lock = asyncio.Lock()

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)

    async def get(self, key: str) -> Optional[CachedResponse]:
        async with self._lock:
            self._purge_expired()
            entry = self._entries.get(key)
            if entry is None or entry.state != "completed":
                return None
            return entry.response

    async def reserve(self, key: str, ttl: int) -> bool:
        async with self._lock:
            self._purge_expired()
            if key in self._entries:
                return False
            self._entries[key] = _StoredEntry(state="pending", expires_at=time.monotonic() + ttl)
            return True

    async def complete(self, key: str, response: CachedResponse, ttl: int) -> None:
        async with self._lock:
            self._purge_expired()
            self._entries[key] = _StoredEntry(
                state="completed",
                response=response,
                expires_at=time.monotonic() + ttl,
            )

    async def release(self, key: str) -> None:
        async with self._lock:
            self._entries.pop(key, None)


class IdempotencyMiddleware:
    """Replay completed mutating requests and reject in-flight duplicates."""

    MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app=None, *, store: IdempotencyStore, ttl: int = 86400):
        self.app = app
        self.store = store
        self.ttl = ttl

    @staticmethod
    def _merge_headers(
        headers: list[tuple[bytes, bytes]],
        extra: list[tuple[bytes, bytes]],
    ) -> list[tuple[bytes, bytes]]:
        merged = []
        index: dict[bytes, int] = {}
        for name, value in headers + extra:
            lowered = name.lower()
            if lowered in index:
                merged[index[lowered]] = (name, value)
            else:
                index[lowered] = len(merged)
                merged.append((name, value))
        return merged

    async def _send_cached_response(
        self,
        send,
        key: str,
        cached: CachedResponse,
    ) -> None:
        headers = self._merge_headers(
            list(cached.headers),
            [
                (b"idempotency-key", key.encode("utf-8")),
                (b"idempotent-replayed", b"true"),
            ],
        )
        await send({"type": "http.response.start", "status": cached.status, "headers": headers})
        await send({"type": "http.response.body", "body": cached.body, "more_body": False})

    async def _send_conflict(self, scope, receive, send, key: str) -> None:
        response = Response(
            body={
                "error": {
                    "type": "idempotency_conflict",
                    "message": "A request with this Idempotency-Key is already in progress.",
                }
            },
            status_code=409,
            headers=[(b"idempotency-key", key.encode("utf-8"))],
        )
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in self.MUTATING_METHODS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        key = (headers.get(b"idempotency-key") or b"").decode("utf-8", "ignore").strip()
        if not key:
            await self.app(scope, receive, send)
            return

        cached = await self.store.get(key)
        if cached is not None:
            await self._send_cached_response(send, key, cached)
            return

        reserved = await self.store.reserve(key, self.ttl)
        if not reserved:
            cached = await self.store.get(key)
            if cached is not None:
                await self._send_cached_response(send, key, cached)
                return
            await self._send_conflict(scope, receive, send, key)
            return

        captured = {"status": 200, "headers": [], "body": bytearray(), "complete": False}

        async def capture_send(message):
            if message["type"] == "http.response.start":
                headers_out = self._merge_headers(
                    list(message.get("headers", [])),
                    [(b"idempotency-key", key.encode("utf-8"))],
                )
                captured["status"] = message["status"]
                captured["headers"] = list(headers_out)
                message = {**message, "headers": headers_out}
            elif message["type"] == "http.response.body":
                captured["body"].extend(message.get("body", b""))
                if not message.get("more_body", False):
                    captured["complete"] = True
            await send(message)

        try:
            await self.app(scope, receive, capture_send)
        except Exception:
            await self.store.release(key)
            raise

        if 200 <= captured["status"] < 300 and captured["complete"]:
            await self.store.complete(
                key,
                CachedResponse(
                    status=captured["status"],
                    headers=list(captured["headers"]),
                    body=bytes(captured["body"]),
                ),
                self.ttl,
            )
            return

        await self.store.release(key)


__all__ = [
    "CachedResponse",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "IdempotencyMiddleware",
]
