import json
import unittest

from neutronapi.base import API
from neutronapi.application import Application


class PingAPI(API):
    resource = ""

    @API.endpoint("/ping", methods=["GET"], name="ping")
    async def ping(self, scope, receive, send, **kwargs):
        return await self.response({"ok": True})


async def call_asgi(app, scope, body: bytes = b""):
    messages = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


class TestErrorShapes(unittest.IsolatedAsyncioTestCase):
    async def test_not_found_shape(self):
        app = Application(apis=[PingAPI()])
        scope = {"type": "http", "method": "GET", "path": "/nope", "headers": []}
        messages = await call_asgi(app, scope)
        self.assertEqual(messages[0]["status"], 404)
        body = json.loads(messages[1].get("body", b"{}").decode() or "{}")
        self.assertIn("error", body)
        self.assertEqual(body["error"].get("type"), "invalid_request_error")
        self.assertIn("Unrecognized request URL.", body["error"].get("message", ""))

    async def test_method_not_allowed_shape(self):
        app = Application(apis=[PingAPI()])
        scope = {"type": "http", "method": "POST", "path": "/ping", "headers": []}
        messages = await call_asgi(app, scope, body=b"{}")
        self.assertEqual(messages[0]["status"], 405)
        body = json.loads(messages[1].get("body", b"{}").decode() or "{}")
        self.assertEqual(body.get("error", {}).get("type"), "method_not_allowed")
        self.assertIn("not allowed", body.get("error", {}).get("message", "").lower())

    async def test_validation_error_shape(self):
        # Endpoint expecting JSON; send invalid JSON
        class EchoAPI(API):
            resource = ""

            @API.endpoint("/echo", methods=["POST"], name="echo")
            async def echo(self, scope, receive, send, **kwargs):
                # If parsing fails, framework raises ValidationError before here
                return await self.response({"ok": True})

        app = Application(apis=[EchoAPI()])
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/echo",
            "headers": [(b"content-type", b"application/json")],
        }
        messages = await call_asgi(app, scope, body=b"{invalid}")
        self.assertEqual(messages[0]["status"], 400)
        body = json.loads(messages[1].get("body", b"{}").decode() or "{}")
        self.assertEqual(body.get("error", {}).get("type"), "validation_error")
        self.assertIn("invalid", body.get("error", {}).get("message", "").lower())

    async def test_auth_and_permission_error_shapes(self):
        class SecureAPI(API):
            resource = ""

            @API.endpoint("/secure", methods=["GET"], name="secure")
            async def secure(self, scope, receive, send, **kwargs):
                return await self.response({"ok": True})

            async def authorize(self, scope):
                # Expect header X-Auth: ok
                headers = dict(scope.get("headers", []))
                if headers.get(b"x-auth") != b"ok":
                    from neutronapi.api import exceptions
                    raise exceptions.AuthenticationFailed("Invalid token")

        app = Application(apis=[SecureAPI(authentication_class=SecureAPI())])

        # 401 without header
        scope = {"type": "http", "method": "GET", "path": "/secure", "headers": []}
        messages = await call_asgi(app, scope)
        self.assertEqual(messages[0]["status"], 401)
        body = json.loads(messages[1].get("body", b"{}").decode() or "{}")
        self.assertEqual(body.get("error", {}).get("type"), "authentication_failed")

        # 403 via permission class
        class DenyAll:
            async def has_permission(self, scope, user):
                return False

        class PermAPI(API):
            resource = ""

            @API.endpoint("/perm", methods=["GET"], name="perm", permission_classes=[DenyAll])
            async def perm(self, scope, receive, send, **kwargs):
                return await self.response({"ok": True})

        app2 = Application(apis=[PermAPI()])
        scope2 = {"type": "http", "method": "GET", "path": "/perm", "headers": []}
        messages2 = await call_asgi(app2, scope2)
        self.assertEqual(messages2[0]["status"], 403)
        body2 = json.loads(messages2[1].get("body", b"{}").decode() or "{}")
        self.assertEqual(body2.get("error", {}).get("type"), "permission_denied")
