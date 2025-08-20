import unittest

from neutronapi.base import API
from neutronapi.application import Application
from neutronapi import exceptions


class DummyAuth:
    async def authorize(self, scope):
        # Simple auth: require header X-Auth: ok
        headers = dict(scope.get("headers", []))
        token = headers.get(b"x-auth")
        if not token or token.decode() != "ok":
            raise exceptions.AuthenticationFailed("Invalid token")


class SecuredAPI(API):
    name = "secure"
    resource = ""
    authentication_class = DummyAuth()

    @API.endpoint("/secure", methods=["GET"], name="secure")
    async def secure(self, scope, receive, send, **kwargs):
        return await self.response({"ok": True})


async def call_asgi(app, scope, body: bytes = b""):
    out = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        out.append(message)

    await app(scope, receive, send)
    return out


class TestAuthenticationWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_auth_required(self):
        app = Application({"secure": SecuredAPI()})
        base_scope = {"type": "http", "method": "GET", "path": "/secure", "headers": []}

        # Missing header → 401
        messages = await call_asgi(app, base_scope)
        self.assertEqual(messages[0]["status"], 401)

        # With header → 200
        scope2 = {**base_scope, "headers": [(b"x-auth", b"ok")]}
        messages = await call_asgi(app, scope2)
        self.assertEqual(messages[0]["status"], 200)

