"""Security remediation tests for NeutronAPI framework.

Tests for vulnerabilities T0-1 through T3-2 identified in the adversarial audit.
"""
import asyncio
import time
import unittest

from neutronapi.base import API, Response
from neutronapi.api import exceptions
from neutronapi.middleware.allowed_hosts import AllowedHostsMiddleware
from neutronapi.middleware.cors import CorsMiddleware
from neutronapi.middleware.routing import RoutingMiddleware
from neutronapi.db.queryset import QuerySet
from neutronapi.idempotency import InMemoryIdempotencyStore, IdempotencyMiddleware
from neutronapi.parsers import BinaryParser
from neutronapi.throttling import SlidingWindowThrottle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummyASGI:
    async def __call__(self, scope, receive, send, **kwargs):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": b"{}"})


async def call_asgi(app, scope, body: bytes = b""):
    out = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        out.append(message)

    await app(scope, receive, send)
    return out


class DummyAuth:
    authorized = True

    @classmethod
    async def authorize(cls, scope):
        if not cls.authorized:
            raise exceptions.AuthenticationFailed("Unauthorized")
        scope["user"] = {"id": "test_user"}


class NullAuth:
    """Auth class that always passes — used to explicitly mark public endpoints."""

    @classmethod
    async def authorize(cls, scope):
        pass


# ---------------------------------------------------------------------------
# T0-1: SQL injection via order_by
# ---------------------------------------------------------------------------

class TestOrderByInjection(unittest.TestCase):
    """T0-1: Ordering field must be validated against allowlist."""

    def test_quote_identifier_rejects_sql_injection(self):
        """Field names containing SQL metacharacters are rejected."""
        with self.assertRaises(ValueError):
            QuerySet._quote_identifier("id; DROP TABLE accounts--")

        with self.assertRaises(ValueError):
            QuerySet._quote_identifier("id OR 1=1")

        with self.assertRaises(ValueError):
            QuerySet._quote_identifier("name'")

    def test_quote_identifier_accepts_valid_names(self):
        self.assertEqual(QuerySet._quote_identifier("id"), '"id"')
        self.assertEqual(QuerySet._quote_identifier("created_at"), '"created_at"')
        self.assertEqual(QuerySet._quote_identifier("name"), '"name"')
        self.assertEqual(QuerySet._quote_identifier("_private"), '"_private"')


class TestOrderingAllowlist(unittest.IsolatedAsyncioTestCase):
    """T0-1: API-level ordering field allowlist validation."""

    async def test_ordering_rejected_when_not_in_allowlist(self):
        """Ordering by a field not in allowed_ordering_fields raises ValidationError."""

        class StrictAPI(API):
            resource = "/v1/test"
            allowed_ordering_fields = ["name", "created_at"]

        api = StrictAPI()
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/test",
            "query_string": b"ordering=malicious_field",
            "headers": [],
        }
        with self.assertRaises(exceptions.ValidationError):
            await api._process_client_params(scope)

    async def test_ordering_accepted_when_in_allowlist(self):
        class StrictAPI(API):
            resource = "/v1/test"
            allowed_ordering_fields = ["name", "created_at"]

        api = StrictAPI()
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/test",
            "query_string": b"ordering=-name",
            "headers": [],
        }
        result = await api._process_client_params(scope)
        self.assertEqual(result["ordering"], "-name")

    async def test_order_direction_validated(self):
        class TestAPI(API):
            resource = "/v1/test"
            allowed_ordering_fields = ["name"]

        api = TestAPI()
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/test",
            "query_string": b"ordering=name&order_direction=INVALID",
            "headers": [],
        }
        with self.assertRaises(exceptions.ValidationError):
            await api._process_client_params(scope)


# ---------------------------------------------------------------------------
# T0-2: Body size limits
# ---------------------------------------------------------------------------

class TestBodySizeLimit(unittest.IsolatedAsyncioTestCase):
    """T0-2: Unbounded request body must be rejected."""

    async def test_oversized_body_returns_413(self):
        """A request body exceeding MAX_BODY_SIZE is rejected with 413."""

        class SmallAPI(API):
            resource = "/v1/small"
            MAX_BODY_SIZE = 100  # 100 bytes

            @API.endpoint("/", methods=["POST"])
            async def create(self, scope, receive, send, **kwargs):
                return Response(body={"ok": True})

        api = SmallAPI()
        large_body = b"x" * 200

        responses = []

        async def receive():
            return {"type": "http.request", "body": large_body, "more_body": False}

        async def send(msg):
            responses.append(msg)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/v1/small",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        }
        await api.handle(scope, receive, send)
        # Should get a 413 response
        self.assertEqual(responses[0]["status"], 413)


# ---------------------------------------------------------------------------
# T0-3: WebSocket auth pipeline
# ---------------------------------------------------------------------------

class TestWebSocketAuth(unittest.IsolatedAsyncioTestCase):
    """T0-3: WebSocket endpoints must run auth/permissions/throttle."""

    async def test_websocket_rejected_without_auth(self):
        """WebSocket to a protected API is rejected with close code 4001."""

        class ProtectedAPI(API):
            resource = "/v1/protected"
            authentication_class = DummyAuth

            @API.websocket("/stream")
            async def stream(self, scope, receive, send, **kwargs):
                pass  # should never reach here

        # Make auth fail
        DummyAuth.authorized = False
        try:
            api = ProtectedAPI()
            messages = []

            async def receive():
                return {"type": "websocket.connect"}

            async def send(msg):
                messages.append(msg)

            scope = {
                "type": "websocket",
                "path": "/v1/protected/stream",
                "headers": [],
            }
            await api.handle_websocket(scope, receive, send)
            self.assertEqual(messages[0]["type"], "websocket.close")
            self.assertEqual(messages[0]["code"], 4001)
        finally:
            DummyAuth.authorized = True


# ---------------------------------------------------------------------------
# T0-4: Middleware WebSocket validation
# ---------------------------------------------------------------------------

class TestMiddlewareWebSocket(unittest.IsolatedAsyncioTestCase):
    """T0-4: AllowedHosts and CORS must validate WebSocket connections."""

    async def test_allowed_hosts_rejects_bad_websocket_host(self):
        app = AllowedHostsMiddleware(DummyASGI(), allowed_hosts=["good.com"])
        messages = []

        async def receive():
            return {"type": "websocket.connect"}

        async def send(msg):
            messages.append(msg)

        scope = {
            "type": "websocket",
            "path": "/ws",
            "headers": [(b"host", b"evil.com")],
        }
        await app(scope, receive, send)
        self.assertEqual(messages[0]["type"], "websocket.close")
        self.assertEqual(messages[0]["code"], 4003)

    async def test_allowed_hosts_passes_good_websocket_host(self):
        reached = []

        class TrackingApp:
            async def __call__(self, scope, receive, send, **kwargs):
                reached.append(True)

        app = AllowedHostsMiddleware(TrackingApp(), allowed_hosts=["good.com"])

        async def receive():
            return {"type": "websocket.connect"}

        async def send(msg):
            pass

        scope = {
            "type": "websocket",
            "path": "/ws",
            "headers": [(b"host", b"good.com")],
        }
        await app(scope, receive, send)
        self.assertTrue(reached)

    async def test_cors_rejects_bad_websocket_origin(self):
        app = CorsMiddleware(
            DummyASGI(),
            allowed_origins=["https://good.com"],
        )
        messages = []

        async def receive():
            return {"type": "websocket.connect"}

        async def send(msg):
            messages.append(msg)

        scope = {
            "type": "websocket",
            "path": "/ws",
            "headers": [
                (b"host", b"api.good.com"),
                (b"origin", b"https://evil.com"),
            ],
        }
        await app(scope, receive, send)
        self.assertEqual(messages[0]["type"], "websocket.close")
        self.assertEqual(messages[0]["code"], 4003)


# ---------------------------------------------------------------------------
# T0-5: CORS defaults
# ---------------------------------------------------------------------------

class TestCORSDefaults(unittest.TestCase):
    """T0-5: CORS must not allow all origins by default."""

    def test_credentials_not_sent_with_allow_all(self):
        """When allow_all_origins=True, credentials header should NOT be sent."""
        cors = CorsMiddleware(DummyASGI(), allow_all_origins=True)
        headers = cors.get_cors_headers("https://anything.com")
        header_names = [name for name, _ in headers]
        self.assertNotIn(b"Access-Control-Allow-Credentials", header_names)

    def test_credentials_sent_with_explicit_allowlist(self):
        """When using explicit origins, credentials header IS sent."""
        cors = CorsMiddleware(
            DummyASGI(),
            allowed_origins=["https://app.com"],
        )
        headers = cors.get_cors_headers("https://app.com")
        header_names = [name for name, _ in headers]
        self.assertIn(b"Access-Control-Allow-Credentials", header_names)


# ---------------------------------------------------------------------------
# T1-1: Route-level authentication override
# ---------------------------------------------------------------------------

class TestRouteLevelAuth(unittest.IsolatedAsyncioTestCase):
    """T1-1: Route-level authentication_class must override API-level auth."""

    async def test_route_level_auth_none_bypasses_api_auth(self):
        """A public endpoint on a protected API should skip auth."""

        class MixedAPI(API):
            resource = "/v1/mixed"
            authentication_class = DummyAuth

            @API.endpoint("/public", methods=["GET"], authentication_class=NullAuth)
            async def public(self, scope, receive, send, **kwargs):
                return Response(body={"public": True})

            @API.endpoint("/private", methods=["GET"])
            async def private(self, scope, receive, send, **kwargs):
                return Response(body={"private": True})

        DummyAuth.authorized = False
        try:
            api = MixedAPI()

            # Public endpoint should work even with auth failing
            responses = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(msg):
                responses.append(msg)

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/v1/mixed/public",
                "query_string": b"",
                "headers": [],
            }
            await api.handle(scope, receive, send)
            self.assertEqual(responses[0]["status"], 200)

            # Private endpoint should fail
            responses.clear()
            scope["path"] = "/v1/mixed/private"
            await api.handle(scope, receive, send)
            self.assertEqual(responses[0]["status"], 401)
        finally:
            DummyAuth.authorized = True


# ---------------------------------------------------------------------------
# T1-4: Pagination bounds
# ---------------------------------------------------------------------------

class TestPaginationBounds(unittest.IsolatedAsyncioTestCase):
    """T1-4: Pagination parameters must be bounded."""

    async def test_page_size_clamped_to_max(self):
        class TestAPI(API):
            resource = "/v1/test"
            MAX_PAGE_SIZE = 50

        api = TestAPI()
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/test",
            "query_string": b"page_size=999999",
            "headers": [],
        }
        result = await api._process_client_params(scope)
        self.assertEqual(result["page_size"], 50)

    async def test_negative_page_clamped_to_1(self):
        api = API(resource="/v1/test")
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/test",
            "query_string": b"page=-5",
            "headers": [],
        }
        result = await api._process_client_params(scope)
        self.assertEqual(result["page"], 1)

    async def test_non_integer_page_raises_validation_error(self):
        api = API(resource="/v1/test")
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/test",
            "query_string": b"page=abc",
            "headers": [],
        }
        with self.assertRaises(exceptions.ValidationError):
            await api._process_client_params(scope)


# ---------------------------------------------------------------------------
# T2-2: Idempotency key limits
# ---------------------------------------------------------------------------

class TestIdempotencyLimits(unittest.IsolatedAsyncioTestCase):
    """T2-2: Idempotency store must enforce key length and entry count limits."""

    async def test_oversized_key_rejected(self):
        store = InMemoryIdempotencyStore(max_key_length=10, max_entries=100)
        app = IdempotencyMiddleware(DummyASGI(), store=store, ttl=60)

        long_key = "x" * 20  # exceeds max_key_length=10
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [(b"idempotency-key", long_key.encode())],
        }
        msgs = await call_asgi(app, scope)
        self.assertEqual(msgs[0]["status"], 400)

    async def test_max_entries_eviction(self):
        store = InMemoryIdempotencyStore(max_key_length=256, max_entries=5)
        # Fill up the store
        for i in range(5):
            await store.reserve(f"key_{i}", ttl=300)

        # 6th entry should succeed via eviction
        result = await store.reserve("key_overflow", ttl=300)
        self.assertTrue(result)
        self.assertLessEqual(len(store._entries), 5)


# ---------------------------------------------------------------------------
# T2-3: BinaryParser JSON fallback
# ---------------------------------------------------------------------------

class TestBinaryParserNoFallback(unittest.IsolatedAsyncioTestCase):
    """T2-3: BinaryParser must not silently fall back on JSON parse failure."""

    async def test_malformed_json_raises_validation_error(self):
        parser = BinaryParser()
        headers = {b"content-type": b"application/json"}
        with self.assertRaises(exceptions.ValidationError):
            await parser.parse(
                scope={},
                receive=None,
                raw_body=b"{invalid json",
                headers=headers,
            )


# ---------------------------------------------------------------------------
# T2-4: Host header not echoed
# ---------------------------------------------------------------------------

class TestHostEchoRemoved(unittest.IsolatedAsyncioTestCase):
    """T2-4: AllowedHosts error must not echo the Host header value."""

    async def test_bad_host_error_does_not_echo_value(self):
        app = AllowedHostsMiddleware(DummyASGI(), allowed_hosts=["good.com"])
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"host", b"<script>alert(1)</script>")],
        }
        msgs = await call_asgi(app, scope)
        body = msgs[1]["body"].decode()
        self.assertNotIn("<script>", body)
        self.assertIn("Invalid Host header", body)


# ---------------------------------------------------------------------------
# T2-5: Routing wildcard anchoring
# ---------------------------------------------------------------------------

class TestRoutingWildcard(unittest.TestCase):
    """T2-5: Wildcard *.example.com must NOT match evil.evil.example.com."""

    def test_wildcard_rejects_nested_subdomains(self):
        import re
        router = RoutingMiddleware(
            default_app=DummyASGI(),
            static_hosts=["*.example.com"],
        )
        # Should match single-level subdomain
        matched = False
        for pattern in router.pattern_hosts:
            if pattern.match("app.example.com"):
                matched = True
        self.assertTrue(matched)

        # Should NOT match nested subdomain
        for pattern in router.pattern_hosts:
            if pattern.match("evil.evil.example.com"):
                self.fail("Nested subdomain matched wildcard — injection risk")


# ---------------------------------------------------------------------------
# T3-2: SlidingWindowThrottle
# ---------------------------------------------------------------------------

class TestSlidingWindowThrottle(unittest.IsolatedAsyncioTestCase):
    """T3-2: Built-in throttle implementation works correctly."""

    async def test_throttle_allows_within_limit(self):
        class TestThrottle(SlidingWindowThrottle):
            rate = "5/second"
            scope_attr = "ip"

        throttle = TestThrottle()
        scope = {"client": ("1.2.3.4", 12345)}

        for _ in range(5):
            result = await throttle.allow_request(scope)
            self.assertTrue(result)

    async def test_throttle_blocks_over_limit(self):
        from collections import defaultdict

        class TestThrottle(SlidingWindowThrottle):
            rate = "3/second"
            scope_attr = "ip"
            _histories = defaultdict(list)  # fresh store for this test

        throttle = TestThrottle()
        scope = {"client": ("9.9.9.9", 12345)}

        for _ in range(3):
            await throttle.allow_request(scope)

        result = await throttle.allow_request(scope)
        self.assertFalse(result)

        wait = await throttle.wait()
        self.assertIsNotNone(wait)
        self.assertGreater(wait, 0)


if __name__ == "__main__":
    unittest.main()
