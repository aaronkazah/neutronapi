import unittest

from neutronapi.middleware.allowed_hosts import AllowedHostsMiddleware
from neutronapi.middleware.cors import CORS


class DummyASGI:
    async def __call__(self, scope, receive, send, **kwargs):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({
            "type": "http.response.body",
            "body": b"{}",
        })


async def call_asgi(app, scope, body: bytes = b""):
    out = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        out.append(message)

    await app(scope, receive, send)
    return out


class TestMiddleware(unittest.IsolatedAsyncioTestCase):
    async def test_allowed_hosts(self):
        app = AllowedHostsMiddleware(DummyASGI(), allowed_hosts=["example.com"])

        scope_ok = {"type": "http", "method": "GET", "path": "/", "headers": [(b"host", b"example.com")]} 
        msgs = await call_asgi(app, scope_ok)
        self.assertEqual(msgs[0]["status"], 200)

        scope_bad = {"type": "http", "method": "GET", "path": "/", "headers": [(b"host", b"bad.com")]}
        msgs = await call_asgi(app, scope_bad)
        self.assertEqual(msgs[0]["status"], 400)

    async def test_cors(self):
        app = CORS(DummyASGI(), allow_all_origins=True)
        scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"origin", b"https://foo")]} 
        msgs = await call_asgi(app, scope)
        self.assertEqual(msgs[0]["status"], 200)
        self.assertIn(b"Access-Control-Allow-Origin", {k for k, _ in msgs[0].get("headers", [])})

