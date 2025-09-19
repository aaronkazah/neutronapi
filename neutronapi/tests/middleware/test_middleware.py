import unittest

from neutronapi.middleware.allowed_hosts import AllowedHostsMiddleware
from neutronapi.middleware.cors import CorsMiddleware


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
        app = CorsMiddleware(DummyASGI(), allow_all_origins=True)
        scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"origin", b"https://foo")]}
        msgs = await call_asgi(app, scope)
        self.assertEqual(msgs[0]["status"], 200)
        self.assertIn(b"Access-Control-Allow-Origin", {k for k, _ in msgs[0].get("headers", [])})

    def test_cors_origin_validation(self):
        # Valid origins should work
        CorsMiddleware(DummyASGI(), allowed_origins=["https://example.com"])
        CorsMiddleware(DummyASGI(), allowed_origins=["http://localhost:3000"])
        CorsMiddleware(DummyASGI(), allowed_origins=["https://*.example.com"])
        CorsMiddleware(DummyASGI(), allowed_origins=["https://*.staging.example.com"])

        # Invalid origins should raise errors with helpful messages
        with self.assertRaisesRegex(ValueError, "must start with 'http://' or 'https://'"):
            CorsMiddleware(DummyASGI(), allowed_origins=["example.com"])

        with self.assertRaisesRegex(ValueError, "should not end with '/'"):
            CorsMiddleware(DummyASGI(), allowed_origins=["https://example.com/"])

        with self.assertRaisesRegex(ValueError, "Invalid wildcard pattern"):
            CorsMiddleware(DummyASGI(), allowed_origins=["https://app.*.com"])

        with self.assertRaisesRegex(ValueError, "Invalid wildcard pattern"):
            CorsMiddleware(DummyASGI(), allowed_origins=["https://*example.com"])

        # Must provide either allow_all or allowed_origins
        with self.assertRaisesRegex(ValueError, "Examples of allowed_origins"):
            CorsMiddleware(DummyASGI())

    async def test_cors_wildcard_matching(self):
        # Test wildcard subdomain matching
        app = CorsMiddleware(
            DummyASGI(),
            allowed_origins=[
                "https://example.com",
                "https://*.example.com",
                "http://localhost:3000"
            ]
        )

        # Test exact match
        scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"origin", b"https://example.com")]}
        msgs = await call_asgi(app, scope)
        self.assertEqual(msgs[0]["status"], 200)
        self.assertIn(b"Access-Control-Allow-Origin", {k for k, _ in msgs[0].get("headers", [])})

        # Test wildcard match
        scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"origin", b"https://app.example.com")]}
        msgs = await call_asgi(app, scope)
        self.assertEqual(msgs[0]["status"], 200)
        self.assertIn(b"Access-Control-Allow-Origin", {k for k, _ in msgs[0].get("headers", [])})

        # Test another wildcard match
        scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"origin", b"https://api.example.com")]}
        msgs = await call_asgi(app, scope)
        self.assertEqual(msgs[0]["status"], 200)
        self.assertIn(b"Access-Control-Allow-Origin", {k for k, _ in msgs[0].get("headers", [])})

        # Test non-matching origin (should not have CORS headers)
        scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"origin", b"https://evil.com")]}
        msgs = await call_asgi(app, scope)
        self.assertEqual(msgs[0]["status"], 200)
        self.assertNotIn(b"Access-Control-Allow-Origin", {k for k, _ in msgs[0].get("headers", [])})

