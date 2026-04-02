import json
import unittest

from neutronapi.application import Application
from neutronapi.base import API
from neutronapi.throttling import BaseThrottle


async def call_asgi(app, scope, body: bytes = b""):
    messages = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


class QuotaThrottle(BaseThrottle):
    async def allow_request(self, scope: dict) -> bool:
        return True

    async def get_headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "87",
            "X-RateLimit-Reset": "1717200000",
        }


class BlockingThrottle(BaseThrottle):
    async def allow_request(self, scope: dict) -> bool:
        return False

    async def wait(self) -> int:
        return 30

    async def get_headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1717200000",
        }


class SecondaryQuotaThrottle(BaseThrottle):
    async def allow_request(self, scope: dict) -> bool:
        return True

    async def get_headers(self) -> dict[str, str]:
        return {"X-RateLimit-Bucket": "secondary"}


class ThrottledAPI(API):
    name = "throttled"
    resource = ""

    @API.endpoint("/ok", methods=["GET"], throttle_classes=[QuotaThrottle, SecondaryQuotaThrottle])
    async def ok(self, scope, receive, send, **kwargs):
        return await self.response({"ok": True})

    @API.endpoint("/limited", methods=["GET"], throttle_classes=[BlockingThrottle])
    async def limited(self, scope, receive, send, **kwargs):
        return await self.response({"ok": True})


class TestThrottleHeaders(unittest.IsolatedAsyncioTestCase):
    async def test_success_response_includes_quota_headers(self):
        app = Application(apis=[ThrottledAPI()])
        messages = await call_asgi(
            app,
            {"type": "http", "method": "GET", "path": "/ok", "headers": []},
        )

        headers = dict(messages[0]["headers"])
        self.assertEqual(messages[0]["status"], 200)
        self.assertEqual(headers[b"x-ratelimit-limit"], b"100")
        self.assertEqual(headers[b"x-ratelimit-remaining"], b"87")
        self.assertEqual(headers[b"x-ratelimit-reset"], b"1717200000")
        self.assertEqual(headers[b"x-ratelimit-bucket"], b"secondary")

    async def test_throttled_response_includes_headers_and_retry_after(self):
        app = Application(apis=[ThrottledAPI()])
        messages = await call_asgi(
            app,
            {"type": "http", "method": "GET", "path": "/limited", "headers": []},
        )

        headers = dict(messages[0]["headers"])
        body = json.loads(messages[1]["body"].decode())

        self.assertEqual(messages[0]["status"], 429)
        self.assertEqual(headers[b"retry-after"], b"30")
        self.assertEqual(headers[b"x-ratelimit-limit"], b"100")
        self.assertEqual(headers[b"x-ratelimit-remaining"], b"0")
        self.assertEqual(headers[b"x-ratelimit-reset"], b"1717200000")
        self.assertEqual(body["error"]["type"], "rate_limit_error")
        self.assertEqual(body["error"]["retry_after"], 30)
