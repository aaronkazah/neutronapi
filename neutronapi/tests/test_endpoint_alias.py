import unittest

from neutronapi.base import API, endpoint
from neutronapi.application import Application


class TestEndpointAlias(unittest.IsolatedAsyncioTestCase):
    async def test_alias_decorator_registers_route(self):
        class HelloAPI(API):
            name = "hello"
            resource = "/hello"

            @endpoint("/", methods=["GET"])
            async def get(self, scope, receive, send, **kwargs):
                return await self.response({"message": "hi"})

        app = Application(apis=[HelloAPI()])

        responses = []

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(resp):
            responses.append(resp)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/hello/",
            "query_string": b"",
            "headers": [],
        }

        await app(scope, receive, send)
        statuses = [r.get("status") for r in responses if isinstance(r, dict) and "status" in r]
        self.assertTrue(any(s and s != 404 for s in statuses))

