"""
Tests for WebSocket routing in Application
"""
import unittest
from neutronapi.base import API
from neutronapi.application import Application


async def call_websocket(app, scope):
    """Helper to call websocket ASGI app and collect messages."""
    messages = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(msg):
        messages.append(msg)

    await app(scope, receive, send)
    return messages


async def call_http(app, scope, body: bytes = b""):
    """Helper to call HTTP ASGI app and collect messages."""
    messages = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


class TestWebSocketRouting(unittest.IsolatedAsyncioTestCase):
    """Test websocket routing behavior in Application class"""

    def test_websocket_decorator_registers_route(self):
        """Test that @websocket decorator registers a route with WEBSOCKET method"""

        class SocketAPI(API):
            resource = "/ws"
            name = "socket"

            @API.websocket("/connect")
            async def connect(self, scope, receive, send, **kwargs):
                pass

        api = SocketAPI()
        websocket_routes = [r for r in api.routes if "WEBSOCKET" in r[2]]
        self.assertEqual(len(websocket_routes), 1)
        self.assertEqual(websocket_routes[0][6], "/ws/connect")

    async def test_application_routes_websocket_to_api(self):
        """Test that Application routes websocket scope to the correct API"""

        class SocketAPI(API):
            resource = "/ws"
            name = "socket"

            @API.websocket("/connect")
            async def connect(self, scope, receive, send, **kwargs):
                await send({"type": "websocket.accept"})
                await send({"type": "websocket.send", "text": "hello"})
                await send({"type": "websocket.close", "code": 1000})

        app = Application(apis=[SocketAPI()])

        scope = {
            "type": "websocket",
            "path": "/ws/connect",
            "query_string": b"",
            "headers": [],
        }

        messages = await call_websocket(app, scope)

        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0]["type"], "websocket.accept")
        self.assertEqual(messages[1]["type"], "websocket.send")
        self.assertEqual(messages[1]["text"], "hello")
        self.assertEqual(messages[2]["type"], "websocket.close")

    async def test_websocket_unmatched_path_closes_connection(self):
        """Test that unmatched websocket paths close with code 4004"""

        class SocketAPI(API):
            resource = "/ws"
            name = "socket"

            @API.websocket("/connect")
            async def connect(self, scope, receive, send, **kwargs):
                pass

        app = Application(apis=[SocketAPI()])

        scope = {
            "type": "websocket",
            "path": "/nonexistent",
            "query_string": b"",
            "headers": [],
        }

        messages = await call_websocket(app, scope)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["type"], "websocket.close")
        self.assertEqual(messages[0]["code"], 4004)

    async def test_websocket_unmatched_endpoint_closes_connection(self):
        """Test that matched API but unmatched endpoint closes with 4004"""

        class SocketAPI(API):
            resource = "/ws"
            name = "socket"

            @API.websocket("/connect")
            async def connect(self, scope, receive, send, **kwargs):
                pass

        app = Application(apis=[SocketAPI()])

        scope = {
            "type": "websocket",
            "path": "/ws/other",
            "query_string": b"",
            "headers": [],
        }

        messages = await call_websocket(app, scope)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["type"], "websocket.close")
        self.assertEqual(messages[0]["code"], 4004)

    async def test_http_still_works_after_websocket_support(self):
        """Test that HTTP routing still works correctly"""

        class TestAPI(API):
            resource = "/api"
            name = "test"

            @API.endpoint("/hello", methods=["GET"])
            async def hello(self, scope, receive, send, **kwargs):
                return await self.response({"message": "hello"})

        app = Application(apis=[TestAPI()])

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/hello",
            "query_string": b"",
            "headers": [],
        }

        messages = await call_http(app, scope)

        self.assertEqual(messages[0]["type"], "http.response.start")
        self.assertEqual(messages[0]["status"], 200)

    async def test_http_and_websocket_can_share_same_path(self):
        """A single resource path can expose HTTP and WebSocket handlers."""

        class SharedAPI(API):
            resource = "/shared"
            name = "shared"

            @API.endpoint("/<str:item_id>", methods=["GET"], name="retrieve")
            async def retrieve(self, scope, receive, send, item_id=None, **kwargs):
                return await self.response({"id": item_id})

            @API.websocket("/<str:item_id>")
            async def connect(self, scope, receive, send, item_id=None, **kwargs):
                await send({"type": "websocket.accept"})
                await send({"type": "websocket.send", "text": item_id})
                await send({"type": "websocket.close", "code": 1000})

        app = Application(apis=[SharedAPI()])

        http_scope = {
            "type": "http",
            "method": "GET",
            "path": "/shared/item-123",
            "query_string": b"",
            "headers": [],
        }
        ws_scope = {
            "type": "websocket",
            "path": "/shared/item-123",
            "query_string": b"",
            "headers": [],
        }

        http_messages = await call_http(app, http_scope)
        ws_messages = await call_websocket(app, ws_scope)

        self.assertEqual(http_messages[0]["status"], 200)
        self.assertEqual(ws_messages[0]["type"], "websocket.accept")
        self.assertEqual(ws_messages[1]["text"], "item-123")


if __name__ == "__main__":
    unittest.main()
