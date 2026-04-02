import json
import logging
import unittest
from io import StringIO

from neutronapi.application import Application
from neutronapi.base import API
from neutronapi.logging import configure_logging


async def call_asgi(app, scope, body: bytes = b""):
    messages = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


class PingAPI(API):
    name = "ping"
    resource = ""

    @API.endpoint("/ping", methods=["GET"])
    async def ping(self, scope, receive, send, **kwargs):
        return await self.response({"ok": True, "request_id": scope.get("request_id")})


class TestRequestLogging(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        logging.getLogger("neutronapi").handlers.clear()

    def tearDown(self):
        logging.getLogger("neutronapi").handlers.clear()

    async def test_request_id_header_and_scope_are_set(self):
        app = Application(apis=[PingAPI()])
        messages = await call_asgi(
            app,
            {"type": "http", "method": "GET", "path": "/ping", "headers": []},
        )

        headers = dict(messages[0]["headers"])
        body = json.loads(messages[1]["body"].decode())

        self.assertIn(b"x-request-id", headers)
        self.assertTrue(headers[b"x-request-id"].decode().startswith("req_"))
        self.assertEqual(body["request_id"], headers[b"x-request-id"].decode())

    async def test_request_logging_emits_structured_events(self):
        buf = StringIO()
        configure_logging(level="INFO", fmt="json", stream=buf)

        app = Application(apis=[PingAPI()])
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/ping",
            "headers": [
                (b"user-agent", b"test-agent"),
                (b"origin", b"https://dashboard.example.com"),
                (b"idempotency-key", b"idem_123"),
            ],
        }
        messages = await call_asgi(app, scope)

        headers = dict(messages[0]["headers"])
        request_id = headers[b"x-request-id"].decode()
        output = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
        events = {entry["event"]: entry for entry in output}

        self.assertIn("request.received", events)
        self.assertIn("request.completed", events)
        self.assertEqual(events["request.completed"]["request_id"], request_id)
        self.assertEqual(events["request.completed"]["path"], "/ping")
        self.assertEqual(events["request.completed"]["status"], 200)
        self.assertEqual(events["request.completed"]["idempotency_key"], "idem_123")
