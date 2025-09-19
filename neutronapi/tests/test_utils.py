"""Test utilities for consistent test database configuration."""
import os


def get_postgres_test_config():
    """Get PostgreSQL test configuration using environment variables with sensible defaults."""
    return {
        'ENGINE': 'asyncpg',
        'NAME': os.getenv('POSTGRES_DB', 'postgres'),
        'USER': os.getenv('POSTGRES_USER', 'postgres'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'postgres'),
        'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'PORT': int(os.getenv('POSTGRES_PORT', '5432')),
    }


def get_sqlite_test_config():
    """Get SQLite test configuration for consistency."""
    return {
        'ENGINE': 'aiosqlite',
        'NAME': ':memory:',
    }


