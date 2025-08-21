"""Database related exceptions."""


class DatabaseException(Exception):
    """Base exception for database-related errors."""
    pass


class DoesNotExist(DatabaseException):
    """Raised when a database object does not exist."""
    pass


class MultipleObjectsReturned(DatabaseException):
    """Raised when multiple objects are returned but only one was expected."""
    pass


class IntegrityError(DatabaseException):
    """Raised when database integrity constraints are violated."""
    pass


class ConnectionError(DatabaseException):
    """Raised when database connection fails."""
    pass


class MigrationException(DatabaseException):
    """Base exception for migration-related errors."""
    pass


class MigrationError(MigrationException):
    """Raised when migration operations fail."""
    pass


class InvalidMigrationError(MigrationException):
    """Raised when migration files are invalid or corrupted."""
    pass