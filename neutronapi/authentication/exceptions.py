"""Authentication related exceptions."""


class AuthenticationException(Exception):
    """Base exception for authentication-related errors."""
    pass


class AuthenticationFailed(AuthenticationException):
    """Raised when authentication fails."""
    pass


class AuthenticationRequired(AuthenticationException):
    """Raised when authentication is required but not provided."""
    pass


class InvalidCredentials(AuthenticationException):
    """Raised when provided credentials are invalid."""
    pass


class TokenExpired(AuthenticationException):
    """Raised when an authentication token has expired."""
    pass