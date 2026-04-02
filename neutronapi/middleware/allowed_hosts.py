from __future__ import annotations

import logging
from typing import Callable, Dict, List

from neutronapi.conf import settings

logger = logging.getLogger(__name__)


class AllowedHostsMiddleware:
    """ALLOWED_HOSTS validation middleware."""

    def __init__(
        self,
        app: Callable | None = None,
        allowed_hosts: List[str] | None = None,
        *,
        debug: bool | None = None,
    ):
        self.app = app
        self._custom_allowed_hosts = allowed_hosts
        self.debug = settings.get("DEBUG", False) if debug is None else debug

    def get_allowed_hosts(self) -> List[str]:
        """Get the allowed hosts list. Can be patched in tests."""
        return self._custom_allowed_hosts or settings.get("ALLOWED_HOSTS", ["*"])

    async def __call__(self, scope: Dict, receive: Callable, send: Callable, **kwargs):
        scope_type = scope["type"]

        # Validate Host header for both HTTP and WebSocket connections
        if scope_type in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            host_header = headers.get(b"host")

            if not host_header:
                if not self.debug:
                    if scope_type == "websocket":
                        await send({"type": "websocket.close", "code": 4003})
                        return
                    await self.send_error_response(
                        send, 400, "Bad Request: Missing Host header"
                    )
                    return
                else:
                    logger.warning(
                        "AllowedHostsMiddleware: request with missing Host header "
                        "passed through in debug mode. This would be rejected in production."
                    )
            else:
                host = host_header.decode("utf-8", "ignore")
                if not self.is_host_allowed(host, self.get_allowed_hosts()):
                    if scope_type == "websocket":
                        await send({"type": "websocket.close", "code": 4003})
                        return
                    await self.send_error_response(
                        send, 400, "Bad Request: Invalid Host header"
                    )
                    return

        await self.app(scope, receive, send, **kwargs)

    def is_host_allowed(self, host: str, allowed_hosts: List[str]) -> bool:
        """Check if a host is in the allowed hosts list."""
        if "*" in allowed_hosts:
            return True

        host_without_port = host.split(":")[0]

        if host in allowed_hosts or host_without_port in allowed_hosts:
            return True

        for allowed_host in allowed_hosts:
            if allowed_host.startswith("."):
                if host.endswith(allowed_host) or host_without_port.endswith(
                    allowed_host
                ):
                    return True
            elif allowed_host.startswith("*."):
                domain = allowed_host[2:]
                if host.endswith("." + domain) or host_without_port.endswith(
                    "." + domain
                ):
                    return True
                if host == domain or host_without_port == domain:
                    return True

        return False

    async def send_error_response(self, send: Callable, status_code: int, message: str):
        """Send an error response."""
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"Content-Type", b"text/plain"),
                    (b"Content-Length", str(len(message.encode())).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": message.encode("utf-8"),
            }
        )

    def reverse(self, name: str, **kwargs) -> str:
        """Delegate reverse to the wrapped app."""
        if self.app is None:
            raise AttributeError("Wrapped app does not have reverse method")
        return self.app.reverse(name, **kwargs)
