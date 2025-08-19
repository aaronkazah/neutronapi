import unittest

from neutronapi.base import API
from neutronapi.openapi.openapi import OpenAPIGenerator


class PingAPI(API):
    name = "ping"
    resource = ""

    @API.endpoint("/ping", methods=["GET"], name="ping")
    async def ping(self, scope, receive, send):
        return await self.response({"ok": True})


class TestOpenAPI(unittest.IsolatedAsyncioTestCase):
    async def test_generate_from_api(self):
        gen = OpenAPIGenerator(title="Test", description="D", version="1.0.0")
        spec = await gen.generate_from_api(PingAPI())
        self.assertIn("paths", spec)
        # Ensure our route is present
        self.assertIn("/ping", spec.get("paths", {}))

