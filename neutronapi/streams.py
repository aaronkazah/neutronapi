from __future__ import annotations

from collections import deque
from typing import AsyncIterator, Deque, Optional

from neutronapi.api import exceptions


class AsyncByteStream:
    """Generic async byte stream wrapping the ASGI receive callable."""

    def __init__(
        self,
        receive,
        *,
        content_length: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> None:
        self._receive = receive
        self._content_length = content_length
        self._max_bytes = max_bytes
        self._buffer: Deque[bytes] = deque()
        self._finished = False
        self._bytes_read = 0

    @property
    def content_length(self) -> Optional[int]:
        return self._content_length

    async def _receive_next_chunk(self) -> bytes:
        if self._finished:
            return b""

        while True:
            message = await self._receive()
            message_type = message.get("type")

            if message_type == "http.disconnect":
                self._finished = True
                return b""

            if message_type != "http.request":
                continue

            chunk = message.get("body", b"") or b""
            self._bytes_read += len(chunk)
            if self._max_bytes is not None and self._bytes_read > self._max_bytes:
                raise exceptions.APIException(
                    "Request body too large",
                    type="request_too_large",
                    status=413,
                )

            if not message.get("more_body", False):
                self._finished = True

            return chunk

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            if self._buffer:
                chunk = self._buffer.popleft()
            else:
                chunk = await self._receive_next_chunk()

            if not chunk:
                if self._finished:
                    break
                continue

            yield chunk

    async def read(self, n: int = -1) -> bytes:
        if n == 0:
            return b""

        if n < 0:
            chunks = []
            async for chunk in self:
                chunks.append(chunk)
            return b"".join(chunks)

        remaining = n
        chunks = []

        while remaining > 0:
            if not self._buffer:
                chunk = await self._receive_next_chunk()
                if chunk:
                    self._buffer.append(chunk)
                elif self._finished:
                    break
                else:
                    continue

            chunk = self._buffer.popleft()
            if len(chunk) <= remaining:
                chunks.append(chunk)
                remaining -= len(chunk)
                continue

            chunks.append(chunk[:remaining])
            self._buffer.appendleft(chunk[remaining:])
            remaining = 0

        return b"".join(chunks)
