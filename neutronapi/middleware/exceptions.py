"""Middleware and HTTP related exceptions."""


class MiddlewareException(Exception):
    """Base exception for middleware-related errors."""
    pass


class CORS_Exception(MiddlewareException):
    """Raised for CORS-related errors."""
    pass


class CompressionError(MiddlewareException):
    """Raised when compression fails."""
    pass


class HostNotAllowed(MiddlewareException):
    """Raised when host is not in allowed hosts."""
    pass


class RoutingException(MiddlewareException):
    """Base exception for routing-related errors."""
    pass


class RouteNotFound(RoutingException):
    """Raised when no route matches the request."""
    pass


class MethodNotAllowed(RoutingException):
    """Raised when HTTP method is not allowed for the route."""
    pass