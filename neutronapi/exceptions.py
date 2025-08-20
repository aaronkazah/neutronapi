"""Unified API exceptions with consistent error payloads."""


class APIException(Exception):
    """Base API exception."""
    status_code = 500

    def __init__(self, message: str, type: str | None = None, status: int | None = None):
        self.message = message
        self.type = type or "error"
        self.status_code = status or self.status_code
        super().__init__(self.message)

    def to_dict(self):
        return {
            "error": {
                "type": self.type,
                "message": self.message,
            }
        }


class ValidationError(APIException):
    """Raised when validation fails."""
    status_code = 400

    def __init__(self, message: str = "Validation error", error_type: str | None = None):
        self.error_type = error_type or "validation_error"
        super().__init__(message)

    def to_dict(self):
        return {
            "error": {
                "type": self.error_type,
                "message": self.message,
            }
        }


class NotFound(APIException):
    """Raised when a resource is not found."""
    status_code = 404

    def __init__(self, message: str | None = None):
        if message is None:
            message = (
                "Unrecognized request URL. If you are trying to list objects, remove the trailing slash. "
                "If you are trying to retrieve an object, make sure you passed a valid (non-empty) identifier in your "
                "code. "
                "Please see https://layerbrain.com/docs."
            )
        super().__init__(message, type="invalid_request_error")


class PermissionDenied(APIException):
    """Raised when permission is denied."""
    status_code = 403

    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, type="permission_denied")


class AuthenticationFailed(APIException):
    """Raised when authentication fails."""
    status_code = 401

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, type="authentication_failed")


class MethodNotAllowed(APIException):
    """Method not allowed exception."""
    status_code = 405

    def __init__(self, method: str = "", path: str = ""):
        # If method looks like a full message, use it directly
        if method and ("not allowed" in method.lower() or "method" in method.lower()):
            message = method
        else:
            message = f"Method '{method}' not allowed for path '{path}'"
        super().__init__(message, type="method_not_allowed")


class Throttled(APIException):
    """Request throttled exception."""
    status_code = 429

    def __init__(self, message: str = "Request throttled", wait: int | None = None):
        self.wait = wait
        super().__init__(message, type="throttled", status=429)


# Note: no non-standard exceptions like ResourceError are defined; rely on APIException if needed.


class DoesNotExist(Exception):
    """Raised when an object does not exist."""
