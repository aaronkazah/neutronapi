# core/api/middleware/allowed_hosts.py
from typing import Callable, List, Dict

# Tolerate absence of project-level settings during library tests
try:
    from apps import settings  # type: ignore
except Exception:  # pragma: no cover - fallback for library-only context
    class _FallbackSettings:
        DEBUG = False
        ALLOWED_HOSTS = ['*']

    settings = _FallbackSettings()  # type: ignore


class AllowedHostsMiddleware:
    """ALLOWED_HOSTS validation middleware."""

    def __init__(self, app: Callable | None = None, allowed_hosts: List[str] = None):
        self.app = app
        self._custom_allowed_hosts = allowed_hosts
        self.debug = getattr(settings, "DEBUG", False)

    def get_allowed_hosts(self) -> List[str]:
        """Get the allowed hosts list. Can be patched in tests."""
        return self._custom_allowed_hosts or settings.ALLOWED_HOSTS

    async def __call__(self, scope: Dict, receive: Callable, send: Callable, **kwargs):
        if scope["type"] != "http":
            await self.app(scope, receive, send, **kwargs)
            return

        # Get the Host header
        headers = dict(scope.get("headers", []))
        host_header = headers.get(b"host")

        if not host_header:
            if not self.debug:
                await self.send_error_response(
                    send, 400, "Bad Request: Missing Host header"
                )
                return
        else:
            host = host_header.decode("utf-8", "ignore")

            # Validate host against allowed hosts
            allowed_hosts = self.get_allowed_hosts()
            if not self.is_host_allowed(host, allowed_hosts):
                await self.send_error_response(
                    send, 400, f"Bad Request: Host '{host}' is not allowed"
                )
                return

        # Host is valid, continue processing
        await self.app(scope, receive, send, **kwargs)

    def is_host_allowed(self, host: str, allowed_hosts: List[str]) -> bool:
        """Check if a host is in the allowed hosts list."""
        if "*" in allowed_hosts:
            return True

        # Remove port from host for comparison if present
        host_without_port = host.split(":")[0]

        # Check exact matches
        if host in allowed_hosts:
            return True

        # Check without port
        if host_without_port in allowed_hosts:
            return True

        # Check for wildcard subdomains
        for allowed_host in allowed_hosts:
            if allowed_host.startswith("."):
                # .example.com should match subdomain.example.com
                if host.endswith(allowed_host) or host_without_port.endswith(
                    allowed_host
                ):
                    return True
            elif allowed_host.startswith("*."):
                # *.example.com should match subdomain.example.com
                domain = allowed_host[2:]  # Remove *.
                if host.endswith("." + domain) or host_without_port.endswith(
                    "." + domain
                ):
                    return True
                # Also match the domain itself (example.com matches *.example.com)
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
        if hasattr(self.app, "reverse"):
            return self.app.reverse(name, **kwargs)
        raise AttributeError("Wrapped app does not have reverse method")
