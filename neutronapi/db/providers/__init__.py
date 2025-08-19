from .base import BaseProvider
from .sqlite import SQLiteProvider
from .postgres import PostgreSQLProvider


def get_provider(config):
    engine = str(config.get('ENGINE', 'aiosqlite')).lower()
    # Explicit engines first
    if engine == 'aiosqlite':
        return SQLiteProvider(config)
    if engine == 'asyncpg':
        return PostgreSQLProvider(config)
    # Backward-compatible aliases
    if engine in ('sqlite',):
        return SQLiteProvider(config)
    if engine in ('postgresql', 'postgres'):
        return PostgreSQLProvider(config)
    else:
        raise ValueError(f"Unsupported database engine: {engine}")

__all__ = [
    'BaseProvider',
    'SQLiteProvider',
    'PostgreSQLProvider',
    'get_provider',
]
