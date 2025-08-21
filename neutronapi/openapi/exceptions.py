"""OpenAPI and Swagger related exceptions."""


class OpenAPIException(Exception):
    """Base exception for OpenAPI-related errors."""
    pass


class InvalidSchemaError(OpenAPIException):
    """Raised when OpenAPI schema is invalid."""
    pass


class SwaggerGenerationError(OpenAPIException):
    """Raised when Swagger documentation generation fails."""
    pass


class ValidationSchemaError(OpenAPIException):
    """Raised when request/response validation against schema fails."""
    pass