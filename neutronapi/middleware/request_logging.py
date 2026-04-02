"""Request lifecycle middleware with request IDs and structured events."""

from __future__ import annotations

import time
from typing import Optional

from neutronapi.conf import settings
from neutronapi.event_bus import events
from neutronapi.events import RequestCompleted, RequestError, RequestReceived
from neutronapi.request_id import generate_request_id


class RequestLoggingMiddleware:
    def __init__(self, app=None):
        self.app = app

    def _header_value(self, headers: dict[bytes, bytes], name: bytes) -> Optional[str]:
        value = headers.get(name)
        if not value:
            return None
        decoded = value.decode("utf-8", "ignore").strip()
        return decoded or None

    def _extract_ip(self, headers: dict[bytes, bytes], scope: dict) -> str:
        # Only trust proxy headers when explicitly configured via TRUSTED_PROXY_HEADERS setting.
        # Without configuration, always use the direct connection IP from scope["client"].
        trusted_headers = settings.get("TRUSTED_PROXY_HEADERS", [])
        if trusted_headers:
            for header_name in trusted_headers:
                header_bytes = header_name.lower().encode("utf-8") if isinstance(header_name, str) else header_name
                forwarded = self._header_value(headers, header_bytes)
                if forwarded:
                    return forwarded.split(",", 1)[0].strip()
        client = scope.get("client") or ("", 0)
        return client[0] or ""

    def _extract_user(self, scope: dict) -> Optional[str]:
        user = scope.get("user")
        if isinstance(user, dict):
            return user.get("email") or user.get("id")
        if isinstance(user, str):
            return user
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = scope.get("request_id") or generate_request_id()
        scope["request_id"] = request_id
        start = time.monotonic()
        headers = dict(scope.get("headers", []))
        response_status: Optional[int] = None
        error_message: Optional[str] = None

        meta = {
            "request_id": request_id,
            "method": scope.get("method", ""),
            "path": scope.get("path", ""),
            "ip": self._extract_ip(headers, scope),
            "user_agent": self._header_value(headers, b"user-agent") or "",
            "origin": self._header_value(headers, b"origin"),
            "idempotency_key": self._header_value(headers, b"idempotency-key"),
            "geo": self._header_value(headers, b"cf-ipcountry"),
        }

        await events.emit(RequestReceived(**meta, user=self._extract_user(scope)))

        async def send_wrapper(message):
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
                response_headers = list(message.get("headers", []))
                if not any(name.lower() == b"x-request-id" for name, _ in response_headers):
                    response_headers.append((b"x-request-id", request_id.encode("utf-8")))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            error_message = str(exc)
            await events.emit(
                RequestError(
                    **meta,
                    user=self._extract_user(scope),
                    status=response_status or 500,
                    error=error_message,
                )
            )
            raise
        finally:
            await events.emit(
                RequestCompleted(
                    **meta,
                    user=self._extract_user(scope),
                    status=response_status or 500,
                    duration_ms=round((time.monotonic() - start) * 1000, 2),
                    error=error_message,
                )
            )


__all__ = ["RequestLoggingMiddleware"]
