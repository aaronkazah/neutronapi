"""Geo enrichment middleware for request scope metadata."""

from __future__ import annotations

import ipaddress
import logging
from pathlib import Path
from typing import Any, Callable, TypedDict

from neutronapi.conf import settings

try:
    import maxminddb
except ImportError:  # pragma: no cover - dependency may be missing in older envs
    maxminddb = None

logger = logging.getLogger(__name__)


class GeoResult(TypedDict):
    country_code: str | None
    region: str | None
    city: str | None
    latitude: float | None
    longitude: float | None


class BaseGeoMiddleware:
    """Base middleware for request-scope geo enrichment."""

    geo_scope_key = "_neutronapi_geo"

    def __init__(self, app: Callable | None = None) -> None:
        self.app = app

    @staticmethod
    def _header_value(headers: dict[bytes, bytes], name: bytes) -> str | None:
        value = headers.get(name)
        if not value:
            return None
        decoded = value.decode("utf-8", "ignore").strip()
        return decoded or None

    @staticmethod
    def _header_name(name: str | bytes) -> bytes:
        if isinstance(name, bytes):
            return name.lower()
        return name.lower().encode("utf-8")

    def extract_client_ip(self, scope: dict[str, Any]) -> str | None:
        headers = dict(scope.get("headers", []))
        for header_name in settings.get("TRUSTED_PROXY_HEADERS", []):
            forwarded = self._header_value(headers, self._header_name(header_name))
            if forwarded:
                return forwarded.split(",", 1)[0].strip() or None
        client = scope.get("client") or ("", 0)
        return client[0] or None

    def public_client_ip(self, scope: dict[str, Any]) -> str | None:
        client_ip = self.extract_client_ip(scope)
        if not client_ip:
            return None
        try:
            parsed = ipaddress.ip_address(client_ip)
        except ValueError:
            return None
        if (
            parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_multicast
            or parsed.is_reserved
            or parsed.is_unspecified
        ):
            return None
        return client_ip

    @staticmethod
    def build_geo_result(
        *,
        country_code: str | None = None,
        region: str | None = None,
        city: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> GeoResult | None:
        geo: GeoResult = {
            "country_code": country_code,
            "region": region,
            "city": city,
            "latitude": latitude,
            "longitude": longitude,
        }
        if not any(value is not None for value in geo.values()):
            return None
        return geo

    async def lookup_geo(self, scope: dict[str, Any]) -> GeoResult | None:
        return None

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable,
        send: Callable,
        **kwargs: Any,
    ) -> None:
        if scope.get("type") != "http" or self.geo_scope_key in scope:
            await self.app(scope, receive, send, **kwargs)
            return

        geo = await self.lookup_geo(scope)
        if geo is not None:
            scope[self.geo_scope_key] = geo
        await self.app(scope, receive, send, **kwargs)


class CloudflareGeoMiddleware(BaseGeoMiddleware):
    """Resolve country code from Cloudflare request headers."""

    header_name = b"cf-ipcountry"

    async def lookup_geo(self, scope: dict[str, Any]) -> GeoResult | None:
        headers = dict(scope.get("headers", []))
        country_code = self._header_value(headers, self.header_name)
        if not country_code:
            return None

        normalized = country_code.upper()
        if len(normalized) != 2 or not normalized.isalpha():
            return None

        return self.build_geo_result(country_code=normalized)


class MaxMindGeoMiddleware(BaseGeoMiddleware):
    """Resolve request geo from a MaxMind MMDB file."""

    def __init__(
        self,
        app: Callable | None = None,
        *,
        database_path: str | Path | None = None,
    ) -> None:
        super().__init__(app=app)
        self.database_path = database_path
        self._reader = None
        self._reader_loaded = False

    def _database_file(self) -> Path | None:
        raw_path = self.database_path or settings.get("GEOIP_DATABASE_PATH")
        if not raw_path:
            return None
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path

    def _get_reader(self):
        if self._reader_loaded:
            return self._reader

        self._reader_loaded = True
        if maxminddb is None:
            return None

        database_path = self._database_file()
        if database_path is None or not database_path.exists():
            return None

        try:
            self._reader = maxminddb.open_database(str(database_path))
        except Exception:
            logger.exception("Failed to open GeoIP database at %s", database_path)
            self._reader = None
        return self._reader

    async def lookup_geo(self, scope: dict[str, Any]) -> GeoResult | None:
        client_ip = self.public_client_ip(scope)
        if not client_ip:
            return None

        reader = self._get_reader()
        if reader is None:
            return None

        try:
            record = reader.get(client_ip) or {}
        except Exception:
            logger.exception("Failed GeoIP lookup for %s", client_ip)
            return None

        location = record.get("location") or {}
        country = record.get("country") or {}
        subdivisions = record.get("subdivisions") or []
        subdivision = subdivisions[0] if subdivisions else {}
        city = record.get("city") or {}

        return self.build_geo_result(
            country_code=country.get("iso_code"),
            region=subdivision.get("names", {}).get("en"),
            city=city.get("names", {}).get("en"),
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
        )


__all__ = [
    "BaseGeoMiddleware",
    "CloudflareGeoMiddleware",
    "GeoResult",
    "MaxMindGeoMiddleware",
]
