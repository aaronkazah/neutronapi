from __future__ import annotations

from . import connection as connection_module
from .providers import get_provider
from .connection import (
    setup_databases,
    get_databases,
    ConnectionsManager,
    Connection,
    DatabaseType,
)
from .models import Model
from .queryset import QuerySet


async def shutdown_all_connections():
    """Shutdown all database connections via the global manager."""
    manager = connection_module.CONNECTIONS
    if manager is not None:
        await manager.close_all()


def __getattr__(name: str):
    if name == 'CONNECTIONS':
        return connection_module.CONNECTIONS
    raise AttributeError(f"module 'neutronapi.db' has no attribute '{name}'")


__all__ = [
    'Model',
    'QuerySet',
    'get_provider',
    'setup_databases',
    'get_databases',
    'CONNECTIONS',
    'ConnectionsManager',
    'Connection',
    'DatabaseType',
    'shutdown_all_connections',
]
