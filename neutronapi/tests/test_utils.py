"""Test utilities for consistent test database configuration."""
import os


def get_postgres_test_config():
    """Get PostgreSQL test configuration using environment variables with sensible defaults."""
    return {
        'ENGINE': 'asyncpg',
        'NAME': os.getenv('PGDATABASE', 'postgres'),
        'USER': os.getenv('PGUSER', 'postgres'),
        'PASSWORD': os.getenv('PGPASSWORD', 'postgres'),
        'HOST': os.getenv('PGHOST', 'localhost'),
        'PORT': int(os.getenv('PGPORT', '5432')),
    }


def get_sqlite_test_config():
    """Get SQLite test configuration for consistency."""
    return {
        'ENGINE': 'aiosqlite',
        'NAME': ':memory:',
    }