import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from neutronapi.middleware.geo import (
    BaseGeoMiddleware,
    CloudflareGeoMiddleware,
    MaxMindGeoMiddleware,
)


class DummyASGI:
    async def __call__(self, scope, receive, send, **kwargs):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b"{}"})


async def call_asgi(app, scope, body: bytes = b""):
    messages = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


class StaticGeoMiddleware(BaseGeoMiddleware):
    async def lookup_geo(self, scope):
        return self.build_geo_result(country_code="CA", city="Toronto")


class TestGeoMiddleware(unittest.IsolatedAsyncioTestCase):
    async def test_maxmind_populates_scope_from_reader(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "GeoLite2-City.mmdb"
            database_path.write_bytes(b"stub")
            reader = Mock()
            reader.get.return_value = {
                "country": {"iso_code": "GB"},
                "subdivisions": [{"names": {"en": "England"}}],
                "city": {"names": {"en": "London"}},
                "location": {"latitude": 51.5072, "longitude": -0.1276},
            }

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [],
                "client": ("8.8.8.8", 12345),
            }

            with patch("neutronapi.middleware.geo.maxminddb") as mocked_maxminddb:
                mocked_maxminddb.open_database.return_value = reader
                middleware = MaxMindGeoMiddleware(
                    DummyASGI(),
                    database_path=database_path,
                )
                await call_asgi(middleware, scope)
                self.assertEqual(scope["_neutronapi_geo"]["city"], "London")
                self.assertEqual(scope["_neutronapi_geo"]["country_code"], "GB")

                another_scope = {
                    "type": "http",
                    "method": "GET",
                    "path": "/again",
                    "headers": [],
                    "client": ("8.8.8.8", 54321),
                }
                await call_asgi(middleware, another_scope)
                mocked_maxminddb.open_database.assert_called_once_with(str(database_path))

    async def test_maxmind_skips_missing_database_and_private_ip(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
        middleware = MaxMindGeoMiddleware(
            DummyASGI(),
            database_path="/tmp/does-not-exist.mmdb",
        )
        await call_asgi(middleware, scope)
        self.assertNotIn("_neutronapi_geo", scope)

    async def test_cloudflare_sets_country_code_only(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cf-ipcountry", b"us")],
            "client": ("127.0.0.1", 12345),
        }
        middleware = CloudflareGeoMiddleware(DummyASGI())
        await call_asgi(middleware, scope)

        self.assertEqual(
            scope["_neutronapi_geo"],
            {
                "country_code": "US",
                "region": None,
                "city": None,
                "latitude": None,
                "longitude": None,
            },
        )

    async def test_cloudflare_fills_when_maxmind_does_not(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cf-ipcountry", b"de")],
            "client": ("127.0.0.1", 12345),
        }
        app = CloudflareGeoMiddleware(DummyASGI())
        app = MaxMindGeoMiddleware(app, database_path="/tmp/missing.mmdb")
        await call_asgi(app, scope)
        self.assertEqual(scope["_neutronapi_geo"]["country_code"], "DE")

    async def test_earlier_geo_middleware_prevents_overwrite(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cf-ipcountry", b"us")],
            "client": ("8.8.8.8", 12345),
        }
        app = CloudflareGeoMiddleware(DummyASGI())
        app = StaticGeoMiddleware(app)
        await call_asgi(app, scope)
        self.assertEqual(scope["_neutronapi_geo"]["country_code"], "CA")
        self.assertEqual(scope["_neutronapi_geo"]["city"], "Toronto")
