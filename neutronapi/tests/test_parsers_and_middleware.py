import json
import unittest
from typing import Callable, Dict

from neutronapi.application import Application
from neutronapi.base import API


class DummyGlobalMiddleware:
    def __init__(self, *, id_tag: str = "G"):
        self.id_tag = id_tag
        self.app = None  # late-bound

    async def __call__(self, scope, receive, send):
        async def wrapped_send(message: Dict):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"X-Global", self.id_tag.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped_send)


class DummyEndpointMiddleware:
    def __init__(self, *, id_tag: str = "E"):
        self.id_tag = id_tag
        self.app = None  # late-bound

    async def __call__(self, scope, receive, send):
        async def wrapped_send(message: Dict):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"X-Endpoint", self.id_tag.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped_send)


async def call_asgi(app: Callable, scope: Dict, body: bytes = b"", headers=None):
    messages = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    if headers:
        scope["headers"] = headers
    await app(scope, receive, send)
    return messages


class TestParsersAndMiddleware(unittest.IsolatedAsyncioTestCase):
    async def test_default_json_parser_and_endpoint_middleware(self):
        class EchoAPI(API):
            name = "echo"
            resource = ""

            @API.endpoint(
                "/echo",
                methods=["POST"],
                # endpoint-level middleware instance
                middlewares=[DummyEndpointMiddleware(id_tag="ep1")],
            )
            async def echo(self, scope, receive, send, **kwargs):
                # Default parser should be JSON when none specified
                data = kwargs["body"]
                return await self.response({"data": data})

        app = Application(
            apis=[EchoAPI()],
            middlewares=[DummyGlobalMiddleware(id_tag="g1")],
        )

        payload = {"hello": "world", "n": 123}
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/echo",
            "headers": [(b"content-type", b"application/json")],
        }
        messages = await call_asgi(
            app, scope=scope, body=json.dumps(payload).encode("utf-8")
        )

        self.assertEqual(messages[0]["status"], 200)
        # Both headers present from global + endpoint middlewares
        hdrs = dict(messages[0]["headers"])
        self.assertIn(b"X-Global", hdrs)
        self.assertIn(b"X-Endpoint", hdrs)

        body = json.loads(messages[1]["body"].decode())
        self.assertEqual(body["data"], payload)

    async def test_form_and_binary_parsers(self):
        from neutronapi.parsers import FormParser, BinaryParser

        class MultiAPI(API):
            name = "multi"
            resource = ""

            @API.endpoint("/form", methods=["POST"], parsers=[FormParser()])
            async def form(self, scope, receive, send, **kwargs):
                return await self.response({"form": kwargs["body"]})

            @API.endpoint("/blob", methods=["POST"], parsers=[BinaryParser()])
            async def blob(self, scope, receive, send, **kwargs):
                data: bytes = kwargs["body"]
                return await self.response({"len": len(data)})

        # imports moved above to be available for decorators

        app = Application(apis=[MultiAPI()])

        # Form URL-encoded
        form_body = b"a=1&b=hello"
        scope_form = {
            "type": "http",
            "method": "POST",
            "path": "/form",
            "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        }
        msgs_form = await call_asgi(app, scope_form, body=form_body)
        self.assertEqual(msgs_form[0]["status"], 200)
        form_out = json.loads(msgs_form[1]["body"].decode())
        self.assertEqual(form_out["form"], {"a": "1", "b": "hello"})

        # Binary
        blob = b"\x00\x01\x02\x03" * 100
        scope_blob = {
            "type": "http",
            "method": "POST",
            "path": "/blob",
            "headers": [(b"content-type", b"application/octet-stream")],
        }
        msgs_blob = await call_asgi(app, scope_blob, body=blob)
        self.assertEqual(msgs_blob[0]["status"], 200)
        blob_out = json.loads(msgs_blob[1]["body"].decode())
        self.assertEqual(blob_out["len"], len(blob))

    async def test_binary_parser_with_json_content_type(self):
        """Test that BinaryParser accepts JSON content-type and returns both raw and parsed data."""
        from neutronapi.parsers import BinaryParser

        class StripeAPI(API):
            name = "stripe"
            resource = ""

            @API.endpoint("/webhook", methods=["POST"], parsers=[BinaryParser()])
            async def webhook(self, scope, receive, send, **kwargs):
                # This should work with the enhanced BinaryParser
                raw_bytes = kwargs["raw"]      # Always available - exact bytes sent
                parsed_json = kwargs["body"]   # Parsed JSON if content-type was application/json
                return await self.response({
                    "has_raw": "raw" in kwargs,
                    "raw_type": type(raw_bytes).__name__,
                    "raw_length": len(raw_bytes),
                    "body_type": type(parsed_json).__name__,
                    "parsed_data": parsed_json
                })

        app = Application(apis=[StripeAPI()])

        # Test with JSON content-type (like Stripe webhooks)
        json_payload = {"id": "evt_test_123", "type": "checkout.session.completed"}
        json_body = json.dumps(json_payload).encode("utf-8")
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/webhook",
            "headers": [(b"content-type", b"application/json")],
        }

        messages = await call_asgi(app, scope, body=json_body)
        self.assertEqual(messages[0]["status"], 200)
        result = json.loads(messages[1]["body"].decode())

        # Test that we get both raw bytes and parsed JSON
        self.assertTrue(result["has_raw"])
        self.assertEqual(result["raw_type"], "bytes")
        self.assertEqual(result["raw_length"], len(json_body))
        self.assertEqual(result["body_type"], "dict")
        self.assertEqual(result["parsed_data"], json_payload)

    async def test_multipart_parser_with_file(self):
        from neutronapi.parsers import MultiPartParser

        class UpAPI(API):
            name = "up"
            resource = ""

            @API.endpoint("/upload", methods=["POST"], parsers=[MultiPartParser()])
            async def upload(self, scope, receive, send, **kwargs):
                return await self.response(
                    {
                        "fields": kwargs["body"],
                        "has_file": kwargs.get("file") is not None,
                        "filename": kwargs.get("filename"),
                        "file_type": kwargs.get("file_content_type"),
                    }
                )

        app = Application(apis=[UpAPI()])

        boundary = "------------------------d74496d66958873e"
        parts = []
        # text field
        parts.append(
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"field1\"\r\n\r\n"
            "value1\r\n"
        )
        # file field
        parts.append(
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"file\"; filename=\"test.txt\"\r\n"
            "Content-Type: text/plain\r\n\r\n"
            "hello world\r\n"
        )
        parts.append(f"--{boundary}--\r\n")
        body = "".join(parts).encode("utf-8")
        headers = [
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode("utf-8")),
        ]
        scope = {"type": "http", "method": "POST", "path": "/upload", "headers": headers}
        msgs = await call_asgi(app, scope, body=body)
        self.assertEqual(msgs[0]["status"], 200)
        out = json.loads(msgs[1]["body"].decode())
        self.assertEqual(out["fields"], {"field1": "value1"})
        self.assertTrue(out["has_file"])
        self.assertEqual(out["filename"], "test.txt")
        self.assertEqual(out["file_type"], "text/plain")

    async def test_compression_gzip_and_skip(self):
        # Create large JSON to trigger compression
        class BigAPI(API):
            name = "big"
            resource = ""

            @API.endpoint("/big", methods=["GET"])
            async def big(self, scope, receive, send, **kwargs):
                data = {"items": list(range(0, 500))}
                return await self.response(data)

            @API.endpoint("/zip", methods=["GET"])
            async def zip(self, scope, receive, send, **kwargs):
                # Incompressible content-type should not be compressed
                payload = b"X" * 5000
                return await self.response(payload, media_type="application/zip")

        # Compose with CompressionMiddleware
        from neutronapi.middleware.compression import CompressionMiddleware
        app = Application(
            apis=[BigAPI()],
            middlewares=[CompressionMiddleware(minimum_size=256)],
        )

        # Request with gzip
        scope_gz = {
            "type": "http",
            "method": "GET",
            "path": "/big",
            "headers": [(b"accept-encoding", b"gzip")],
        }
        msgs_gz = await call_asgi(app, scope_gz)
        self.assertEqual(msgs_gz[0]["status"], 200)
        hdrs = dict(msgs_gz[0]["headers"])
        self.assertEqual(hdrs.get(b"content-encoding"), b"gzip")
        self.assertIn(b"Accept-Encoding", hdrs.get(b"vary", b""))
        # Body should be compressed (not JSON plain text)
        self.assertNotIn(b"items", msgs_gz[1]["body"])  # sanity check

        # No Accept-Encoding → no compression
        scope_plain = {"type": "http", "method": "GET", "path": "/big", "headers": []}
        msgs_plain = await call_asgi(app, scope_plain)
        hdrs_plain = dict(msgs_plain[0]["headers"])
        self.assertIsNone(hdrs_plain.get(b"content-encoding"))

        # Incompressible content type should not be compressed even with header
        scope_zip = {
            "type": "http",
            "method": "GET",
            "path": "/zip",
            "headers": [(b"accept-encoding", b"gzip"), (b"accept", b"*/*")],
        }
        msgs_zip = await call_asgi(app, scope_zip)
        hdrs_zip = dict(msgs_zip[0]["headers"])
        self.assertIsNone(hdrs_zip.get(b"content-encoding"))

    async def test_endpoint_and_global_middleware_multiple(self):
        class HeadersAPI(API):
            name = "headers"
            resource = ""

            @API.endpoint(
                "/h",
                methods=["GET"],
                middlewares=[DummyEndpointMiddleware(id_tag="e1"), DummyEndpointMiddleware(id_tag="e2")],
            )
            async def h(self, scope, receive, send, **kwargs):
                return await self.response({"ok": True})

        g1 = DummyGlobalMiddleware(id_tag="g1")
        g2 = DummyGlobalMiddleware(id_tag="g2")
        app = Application(apis=[HeadersAPI()], middlewares=[g1, g2])
        scope = {"type": "http", "method": "GET", "path": "/h", "headers": []}
        msgs = await call_asgi(app, scope)
        hdrs = dict(msgs[0]["headers"])
        self.assertIn(b"X-Global", hdrs)
        # Multiple endpoint headers should appear (last one may overwrite, so check presence via duplicates)
        # Collect multiple X-Endpoint headers
        endpoint_hdrs = [v for (k, v) in msgs[0]["headers"] if k == b"X-Endpoint"]
        self.assertGreaterEqual(len(endpoint_hdrs), 2)

    async def test_services_singleton_shared_across_apis(self):
        class DummyService:
            def __init__(self, *, id: str):
                self.id = id

        shared = DummyService(id="shared")

        class A(API):
            name = "a"
            resource = "/a"
            @API.endpoint("/", methods=["GET"])
            async def a(self, scope, receive, send, **kwargs):
                return await self.response({"sid": id(self.registry["services:shared"])})

        class B(API):
            name = "b"
            resource = "/b"
            @API.endpoint("/", methods=["GET"])
            async def b(self, scope, receive, send, **kwargs):
                return await self.response({"sid": id(self.registry["services:shared"])})

        app = Application(apis=[A(), B()], registry={"services:shared": shared})

        scope_a = {"type": "http", "method": "GET", "path": "/a", "headers": []}
        scope_b = {"type": "http", "method": "GET", "path": "/b", "headers": []}

        ma = await call_asgi(app, scope_a)
        mb = await call_asgi(app, scope_b)

        ida = json.loads(ma[1]["body"].decode())["sid"]
        idb = json.loads(mb[1]["body"].decode())["sid"]
        self.assertEqual(ida, idb)
