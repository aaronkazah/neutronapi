# core/api/middleware/cors.py
from typing import Callable, List, Dict, Tuple, Optional, Any
import re


class CorsMiddleware:
    """CORS (Cross-Origin Resource Sharing) middleware for handling cross-origin requests.

    Args:
        app: The ASGI application to wrap
        allowed_origins: List of allowed origin URLs. Examples:
            - "https://example.com" (specific domain)
            - "http://localhost:3000" (local development)
            - "https://*.example.com" (wildcard subdomain)
            - "https://*.staging.example.com" (nested wildcard subdomain)
        allow_all_origins: If True, allows requests from any origin (use with caution in production)

    Examples:
        # Allow specific origins (recommended for production)
        cors = CorsMiddleware(
            app,
            allowed_origins=[
                "https://example.com",
                "https://app.example.com",
                "https://*.example.com",  # Matches any subdomain
                "http://localhost:3000"
            ]
        )

        # Allow all origins (only for development)
        cors = CorsMiddleware(app, allow_all_origins=True)
    """

    def __init__(
        self,
        app: Optional[Callable] = None,
        allowed_origins: Optional[List[str]] = None,
        allow_all_origins: bool = False,
    ) -> None:
        self.app = app
        self.allowed_origins = allowed_origins or []
        self.allow_all_origins = allow_all_origins

        if not allow_all_origins and not allowed_origins:
            raise ValueError(
                "Either 'allow_all_origins' must be True or 'allowed_origins' must be provided.\n"
                "Examples of allowed_origins:\n"
                '  ["https://example.com", "http://localhost:3000"]'
            )

        # Validate origin format and compile wildcard patterns
        self.origin_patterns = []
        if allowed_origins:
            for origin in allowed_origins:
                self._validate_origin_format(origin)
                if '*' in origin:
                    # Convert wildcard to regex pattern
                    pattern = self._wildcard_to_regex(origin)
                    self.origin_patterns.append((re.compile(pattern), origin))

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable, **kwargs: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send, **kwargs)
            return

        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode("utf-8", "ignore")

        if scope["method"] == "OPTIONS":
            # Handle OPTIONS directly and do not forward to Thalamus
            if self.is_origin_allowed(origin):
                await self.handle_preflight(origin, send)
            else:
                await self.send_error_response(send, 403, "Forbidden")
            return  # Ensure no further processing for OPTIONS requests
        else:
            # Regular requests are processed as before
            kwargs["origin"] = origin
            await self.handle_simple(scope, receive, send, **kwargs)

    async def handle_preflight(self, origin: str, send: Callable):
        response_headers = [
            (b"Access-Control-Allow-Origin", origin.encode("utf-8")),
            (b"Access-Control-Allow-Credentials", b"True"),
            (
                b"Access-Control-Allow-Methods",
                b"GET, POST, PUT, PATCH, DELETE, OPTIONS",
            ),
            (b"Access-Control-Allow-Headers", b"Content-Type, Authorization"),
            (b"Access-Control-Max-Age", b"3600"),
            (b"Vary", b"Origin"),
            (b"Content-Length", b"0"),
        ]
        await send(
            {
                "type": "http.response.start",
                "status": 204,
                "headers": response_headers,
            }
        )
        await send({"type": "http.response.body", "body": b""})

    async def handle_simple(
        self, scope: Dict, receive: Callable, send: Callable, **kwargs
    ):
        origin = kwargs.get("origin")

        async def wrapped_send(response: Dict):
            if response["type"] == "http.response.start":
                if self.is_origin_allowed(origin):
                    response_headers = response.get("headers", [])
                    response_headers.extend(self.get_cors_headers(origin))
                    response["headers"] = response_headers
            await send(response)

        await self.app(scope, receive, wrapped_send)

    async def send_error_response(self, send: Callable, status_code: int, message: str):
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [(b"Content-Type", b"text/plain")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": message.encode("utf-8"),
            }
        )

    def is_origin_allowed(self, origin: str) -> bool:
        if self.allow_all_origins:
            return True
        if not self.allowed_origins:
            return False

        # Check exact matches first
        if origin in self.allowed_origins:
            return True

        # Check wildcard patterns
        for pattern, _ in self.origin_patterns:
            if pattern.match(origin):
                return True

        return False

    def get_cors_headers(self, origin: str) -> List[Tuple[bytes, bytes]]:
        return [
            (b"Access-Control-Allow-Origin", origin.encode("utf-8")),
            (b"Access-Control-Allow-Credentials", b"True"),
            (b"Vary", b"Origin"),
        ]

    def _validate_origin_format(self, origin: str) -> None:
        """Validate that an origin follows the correct format.

        Valid formats:
        - http://domain.com
        - https://domain.com
        - http://localhost:port
        - https://subdomain.domain.com

        Invalid formats:
        - domain.com (missing protocol)
        - http://domain.com/ (trailing slash)
        - *.domain.com (wildcards not yet supported)
        """
        if not origin:
            raise ValueError("Origin cannot be empty")

        if origin.endswith('/'):
            raise ValueError(
                f"Origin '{origin}' should not end with '/'. "
                f"Use '{origin[:-1]}' instead."
            )

        if not origin.startswith(('http://', 'https://')):
            raise ValueError(
                f"Origin '{origin}' must start with 'http://' or 'https://'. "
                f"Example: 'https://{origin}'"
            )

        if '*' in origin:
            # Validate wildcard format
            if not self._is_valid_wildcard_pattern(origin):
                raise ValueError(
                    f"Invalid wildcard pattern '{origin}'. "
                    f"Wildcards are only allowed as '*.domain.com' format. "
                    f"Example: 'https://*.example.com'"
                )

    def _is_valid_wildcard_pattern(self, origin: str) -> bool:
        """Check if wildcard pattern is valid.

        Valid: https://*.example.com, http://*.staging.example.com
        Invalid: https://app.*.com, https://*example.com
        """
        # Remove protocol
        if origin.startswith('https://'):
            domain = origin[8:]
        elif origin.startswith('http://'):
            domain = origin[7:]
        else:
            return False

        # Check wildcard is only at the beginning as a full subdomain
        if domain.startswith('*.'):
            # Valid wildcard subdomain
            return '.*' not in domain[2:] and '*' not in domain[2:]

        return False

    def _wildcard_to_regex(self, pattern: str) -> str:
        r"""Convert a wildcard origin pattern to regex.

        Example: 'https://*.example.com' -> r'^https://[^.]+\.example\.com$'
        """
        # Escape special regex characters except *
        escaped = re.escape(pattern)
        # Replace escaped wildcard with regex pattern for subdomain
        # \* becomes [^.]+ (one or more non-dot characters)
        regex_pattern = escaped.replace(r'\*', r'[^.]+')
        return f'^{regex_pattern}$'

    def reverse(self, name: str, **kwargs) -> str:
        return self.app.reverse(name, **kwargs)
