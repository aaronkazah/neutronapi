# core/api/middleware/cors.py
from typing import Callable, List, Dict, Tuple, Optional, Any


class CORS:
    def __init__(
        self,
        router: Optional[Callable] = None,
        allowed_origins: Optional[List[str]] = None,
        allow_all_origins: bool = False,
    ) -> None:
        self.router = router
        self.allowed_origins = allowed_origins
        self.allow_all_origins = allow_all_origins

        if not allow_all_origins and allowed_origins is None:
            raise ValueError(
                "Either 'allow_all_origins' must be True or 'allowed_origins' must be provided."
            )

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable, **kwargs: Any) -> None:
        if scope["type"] != "http":
            await self.router(scope, receive, send, **kwargs)
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

        await self.router(scope, receive, wrapped_send)

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
        if self.allowed_origins:
            return origin in self.allowed_origins
        return False

    def get_cors_headers(self, origin: str) -> List[Tuple[bytes, bytes]]:
        return [
            (b"Access-Control-Allow-Origin", origin.encode("utf-8")),
            (b"Access-Control-Allow-Credentials", b"True"),
            (b"Vary", b"Origin"),
        ]

    def reverse(self, name: str, **kwargs) -> str:
        return self.router.reverse(name, **kwargs)
