"""
Database connections manager and connection wrapper.

Provides:
- DatabaseType enum
- Connection wrapper exposing provider + execute/fetch/commit/rollback/close
- ConnectionsManager with get_connection() and a simple router
- setup_databases()/get_databases() compatibility helpers
"""
from __future__ import annotations

import os
from enum import Enum
from typing import Dict, Any, Optional

from .providers import SQLiteProvider, PostgreSQLProvider
from neutronapi.conf import ImproperlyConfigured


class DatabaseType(Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class DatabaseRouter:
    def __init__(self, routing_config: Optional[Dict[str, str]] = None):
        self.routing_config = routing_config or {}

    def db_for_app(self, app_label: str) -> str:
        return self.routing_config.get(app_label, 'default')


def _normalize_engine(value: str) -> str:
    """Normalize ENGINE strings to internal identifiers.
    Accepts Django-style engine paths and common aliases.
    Returns one of: 'aiosqlite' or 'asyncpg'.
    """
    e = (value or '').lower().strip()
    if e in (
        'django.db.backends.sqlite3', 'sqlite3', 'sqlite', 'aiosqlite'
    ):
        return 'aiosqlite'
    if e in (
        'django.db.backends.postgresql', 'django.db.backends.postgresql_psycopg2',
        'postgres', 'postgresql', 'psycopg2', 'asyncpg'
    ):
        return 'asyncpg'
    return e or 'aiosqlite'


class Connection:
    def __init__(self, alias: str, config: Dict[str, Any], provider):
        self.alias = alias
        self.config = config
        self.provider = provider
        engine = _normalize_engine(config.get('ENGINE', 'aiosqlite'))
        if engine not in ('aiosqlite', 'asyncpg'):
            raise ValueError(f"Unsupported database engine: {engine}. Allowed: aiosqlite, asyncpg")
        self.db_type = DatabaseType.POSTGRES if engine == 'asyncpg' else DatabaseType.SQLITE

    @classmethod
    async def create(cls, alias: str, config: Dict[str, Any]) -> 'Connection':
        engine = _normalize_engine(config.get('ENGINE', 'aiosqlite'))
        if engine not in ('aiosqlite', 'asyncpg'):
            raise ValueError(f"Unsupported database engine: {engine}. Allowed: aiosqlite, asyncpg")
        if engine == 'aiosqlite':
            provider = SQLiteProvider(config)
        elif engine == 'asyncpg':
            provider = PostgreSQLProvider(config)
        await provider.connect()
        return cls(alias, config, provider)

    # Thin wrappers for provider API
    async def execute(self, query: str, values=()):
        return await self.provider.execute(query, tuple(values))

    async def fetch_one(self, query: str, values=()):
        return await self.provider.fetchone(query, tuple(values))

    async def fetch_all(self, query: str, values=()):
        return await self.provider.fetchall(query, tuple(values))

    async def commit(self):
        # Providers auto-commit; keep for compatibility
        pass

    async def rollback(self):
        pass

    async def close(self):
        await self.provider.disconnect()


class ConnectionsManager:
    def __init__(self, config: Optional[Dict[str, Dict[str, Any]]] = None):
        if config is None:
            # Use settings.DATABASES as the only source of truth
            from neutronapi.conf import settings
            if not hasattr(settings, 'DATABASES'):
                raise ImproperlyConfigured(
                    "DATABASES setting is required. Please define DATABASES in your settings module."
                )
            config = settings.DATABASES
            
        self.config = config
        self.router = DatabaseRouter()
        self._connections: Dict[str, Connection] = {}

    async def get_connection(self, alias: str = 'default') -> Connection:
        if alias not in self._connections:
            cfg = self.config.get(alias, self.config['default'])
            self._connections[alias] = await Connection.create(alias, cfg)
        return self._connections[alias]

    async def close_all(self):
        for conn in list(self._connections.values()):
            try:
                await conn.close()
            except Exception:
                pass
        self._connections.clear()


# Global connection manager
CONNECTIONS: Optional[ConnectionsManager] = None


def setup_databases(config: Optional[Dict[str, Dict[str, Any]]] = None) -> ConnectionsManager:
    global CONNECTIONS
    CONNECTIONS = ConnectionsManager(config)
    return CONNECTIONS


def get_databases() -> ConnectionsManager:
    global CONNECTIONS
    if CONNECTIONS is None:
        # Try to load database configuration from settings
        try:
            from neutronapi.conf import settings
            if hasattr(settings, 'DATABASES'):
                CONNECTIONS = ConnectionsManager(settings.DATABASES)
            else:
                CONNECTIONS = ConnectionsManager()
        except Exception:
            # If settings import fails, use default configuration
            CONNECTIONS = ConnectionsManager()
    return CONNECTIONS
