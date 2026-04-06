from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Tuple


HeaderTuples = List[Tuple[bytes, bytes]]


class StreamingResponse:
    """Generic async chunked response."""

    def __init__(
        self,
        body: AsyncIterator[bytes],
        status: int = 200,
        headers: Optional[Dict[str, Any] | HeaderTuples] = None,
    ) -> None:
        self.body = body
        self.status = status
        self.headers = self._normalize_headers(headers)

    @staticmethod
    def _normalize_headers(
        headers: Optional[Dict[str, Any] | HeaderTuples],
    ) -> HeaderTuples:
        if headers is None:
            return []
        if isinstance(headers, dict):
            return [
                (str(name).lower().encode("utf-8"), str(value).encode("utf-8"))
                for name, value in headers.items()
            ]
        return list(headers)

    async def __call__(self, scope, receive, send) -> None:
        await self.send(send)

    async def send(self, send_callable) -> None:
        await send_callable(
            {
                "type": "http.response.start",
                "status": self.status,
                "headers": self.headers,
            }
        )

        async for chunk in self.body:
            if not isinstance(chunk, bytes):
                chunk = str(chunk).encode("utf-8")
            await send_callable(
                {
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": True,
                }
            )

        await send_callable(
            {
                "type": "http.response.body",
                "body": b"",
                "more_body": False,
            }
        )
