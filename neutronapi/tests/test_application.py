import asyncio
import unittest

from neutronapi.base import API
from neutronapi.application import Application, create_application


class PingAPI(API):
    name = "ping"
    resource = ""

    @API.endpoint("/ping", methods=["GET"], name="ping")
    async def ping(self, scope, receive, send, **kwargs):
        return await self.response({"ok": True, "path": scope.get("path")})


async def call_asgi(app, scope, body: bytes = b""):
    messages = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


class TestAPIAndApplication(unittest.IsolatedAsyncioTestCase):
    async def test_api_reverse(self):
        api = PingAPI()
        url = api.reverse("ping")
        self.assertEqual(url, "/ping")

    async def test_application_basic_request(self):
        app = Application({"ping": PingAPI()})

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/ping",
            "headers": [],
        }

        messages = await call_asgi(app, scope)
        # Expect start + body
        self.assertEqual(messages[0]["type"], "http.response.start")
        self.assertEqual(messages[0]["status"], 200)
        self.assertEqual(messages[1]["type"], "http.response.body")

    async def test_create_application_wrapper(self):
        app = create_application({"ping": PingAPI()})
        scope = {"type": "http", "method": "GET", "path": "/ping", "headers": []}
        messages = await call_asgi(app, scope)
        self.assertEqual(messages[0]["status"], 200)

