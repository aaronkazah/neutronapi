import asyncio
import json
import time
import unittest

from neutronapi.application import Application
from neutronapi.base import API
from neutronapi.idempotency import IdempotencyMiddleware, InMemoryIdempotencyStore


async def call_asgi(app, scope, body: bytes = b""):
    messages = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


class CounterAPI(API):
    name = "counter"
    resource = ""

    counter = 0
    started = None
    release = None

    @API.endpoint("/counter", methods=["POST"])
    async def create(self, scope, receive, send, **kwargs):
        type(self).counter += 1
        return await self.response({"count": type(self).counter})

    @API.endpoint("/slow", methods=["POST"])
    async def slow(self, scope, receive, send, **kwargs):
        type(self).started.set()
        await type(self).release.wait()
        type(self).counter += 1
        return await self.response({"count": type(self).counter})

    @API.endpoint("/counter", methods=["GET"])
    async def read(self, scope, receive, send, **kwargs):
        type(self).counter += 1
        return await self.response({"count": type(self).counter})


class TestIdempotencyMiddleware(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        CounterAPI.counter = 0
        CounterAPI.started = asyncio.Event()
        CounterAPI.release = asyncio.Event()
        self.store = InMemoryIdempotencyStore()
        self.app = Application(
            apis=[CounterAPI()],
            middlewares=[IdempotencyMiddleware(store=self.store, ttl=60)],
        )

    async def test_replays_completed_response(self):
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/counter",
            "headers": [(b"idempotency-key", b"idem_1")],
        }
        first = await call_asgi(self.app, scope)
        second = await call_asgi(self.app, scope)

        first_body = json.loads(first[1]["body"].decode())
        second_body = json.loads(second[1]["body"].decode())
        second_headers = dict(second[0]["headers"])

        self.assertEqual(first_body["count"], 1)
        self.assertEqual(second_body["count"], 1)
        self.assertEqual(second_headers[b"idempotent-replayed"], b"true")

    async def test_concurrent_duplicate_request_is_rejected(self):
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/slow",
            "headers": [(b"idempotency-key", b"idem_2")],
        }

        first_task = asyncio.create_task(call_asgi(self.app, scope))
        await asyncio.wait_for(CounterAPI.started.wait(), timeout=1)
        second = await call_asgi(self.app, scope)
        CounterAPI.release.set()
        first = await asyncio.wait_for(first_task, timeout=1)

        self.assertEqual(first[0]["status"], 200)
        self.assertEqual(second[0]["status"], 409)
        body = json.loads(second[1]["body"].decode())
        self.assertEqual(body["error"]["type"], "idempotency_conflict")

    async def test_safe_methods_bypass_idempotency(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/counter",
            "headers": [(b"idempotency-key", b"idem_get")],
        }

        first = await call_asgi(self.app, scope)
        second = await call_asgi(self.app, scope)

        first_body = json.loads(first[1]["body"].decode())
        second_body = json.loads(second[1]["body"].decode())
        self.assertEqual(first_body["count"], 1)
        self.assertEqual(second_body["count"], 2)

    async def test_store_ttl_expiry_removes_completed_entry(self):
        from neutronapi.idempotency import CachedResponse

        await self.store.reserve("idem_3", ttl=60)
        await self.store.complete(
            "idem_3",
            CachedResponse(status=200, headers=[], body=b"{}"),
            ttl=60,
        )
        self.store._entries["idem_3"].expires_at = time.monotonic() - 1
        self.assertIsNone(await self.store.get("idem_3"))
