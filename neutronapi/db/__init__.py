from .providers import get_provider
from .connection import (
    setup_databases,
    get_databases,
    CONNECTIONS,
    ConnectionsManager,
    Connection,
    DatabaseType,
)
from .models import Model
from .queryset import QuerySet


async def shutdown_all_connections():
    """Shutdown all database connections via the global manager."""
    global CONNECTIONS
    if CONNECTIONS:
        await CONNECTIONS.close_all()


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
