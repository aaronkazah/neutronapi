import json
import unittest

from neutronapi.base import API
from neutronapi.responses import StreamingResponse


async def call_api(api, scope, body_chunks=None):
    messages = []
    chunks = list(body_chunks or [])
    index = 0

    async def receive():
        nonlocal index
        if index < len(chunks):
            chunk = chunks[index]
            index += 1
            return {
                "type": "http.request",
                "body": chunk,
                "more_body": index < len(chunks),
            }
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await api.handle(scope, receive, send)
    return messages


class DummyAuth:
    @classmethod
    async def authorize(cls, scope):
        scope["user"] = {"id": "usr_stream"}


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_streamed_route_receives_async_byte_stream(self):
        class StreamAPI(API):
            resource = "/v1/stream"
            authentication_class = DummyAuth

            @API.endpoint("/", methods=["PUT"], request_body_mode="streamed")
            async def put(self, scope, receive, send, **kwargs):
                received = []
                async for chunk in kwargs["stream"]:
                    received.append(chunk)
                return await self.response(
                    {
                        "joined": b"".join(received).decode("utf-8"),
                        "has_body": "body" in kwargs,
                        "has_raw": "raw" in kwargs,
                        "user": scope["user"]["id"],
                    }
                )

        api = StreamAPI()
        messages = await call_api(
            api,
            {
                "type": "http",
                "method": "PUT",
                "path": "/v1/stream",
                "query_string": b"",
                "headers": [(b"content-length", b"4")],
            },
            body_chunks=[b"ab", b"cd"],
        )

        self.assertEqual(messages[0]["status"], 200)
        payload = json.loads(messages[1]["body"].decode("utf-8"))
        self.assertEqual(payload["joined"], "abcd")
        self.assertFalse(payload["has_body"])
        self.assertFalse(payload["has_raw"])
        self.assertEqual(payload["user"], "usr_stream")

    async def test_streaming_response_sends_multiple_body_frames(self):
        class StreamAPI(API):
            resource = "/v1/stream"

            @API.endpoint("/", methods=["GET"], response_body_mode="streamed")
            async def get(self, scope, receive, send, **kwargs):
                async def chunks():
                    yield b"hello"
                    yield b" "
                    yield b"world"

                return StreamingResponse(
                    chunks(),
                    status=206,
                    headers={"content-type": "text/plain"},
                )

        api = StreamAPI()
        messages = await call_api(
            api,
            {
                "type": "http",
                "method": "GET",
                "path": "/v1/stream",
                "query_string": b"",
                "headers": [],
            },
        )

        self.assertEqual(messages[0]["status"], 206)
        self.assertEqual(messages[1]["body"], b"hello")
        self.assertTrue(messages[1]["more_body"])
        self.assertEqual(messages[2]["body"], b" ")
        self.assertEqual(messages[3]["body"], b"world")
        self.assertFalse(messages[4]["more_body"])

    async def test_buffered_routes_keep_existing_parser_behavior(self):
        class BufferedAPI(API):
            resource = "/v1/buffered"

            @API.endpoint("/", methods=["POST"])
            async def post(self, scope, receive, send, **kwargs):
                return await self.response({"value": kwargs["body"]["value"]})

        api = BufferedAPI()
        messages = await call_api(
            api,
            {
                "type": "http",
                "method": "POST",
                "path": "/v1/buffered",
                "query_string": b"",
                "headers": [(b"content-type", b"application/json")],
            },
            body_chunks=[json.dumps({"value": 42}).encode("utf-8")],
        )

        self.assertEqual(messages[0]["status"], 200)
        payload = json.loads(messages[1]["body"].decode("utf-8"))
        self.assertEqual(payload["value"], 42)

    async def test_streamed_routes_enforce_per_endpoint_size_limit(self):
        class LimitedAPI(API):
            resource = "/v1/limited"

            @API.endpoint(
                "/",
                methods=["PUT"],
                request_body_mode="streamed",
                max_request_body_bytes=3,
            )
            async def put(self, scope, receive, send, **kwargs):
                async for _ in kwargs["stream"]:
                    pass
                return await self.response({"ok": True})

        api = LimitedAPI()
        messages = await call_api(
            api,
            {
                "type": "http",
                "method": "PUT",
                "path": "/v1/limited",
                "query_string": b"",
                "headers": [(b"content-length", b"4")],
            },
            body_chunks=[b"ab", b"cd"],
        )

        self.assertEqual(messages[0]["status"], 413)
