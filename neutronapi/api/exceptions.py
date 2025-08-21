"""API-specific exceptions."""

from typing import Dict, Optional


class APIException(Exception):
    """Base API exception."""
    status_code = 500

    def __init__(self, message: str, type: Optional[str] = None, status: Optional[int] = None) -> None:
        self.message = message
        self.type = type or "error"
        self.status_code = status or self.status_code
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Dict[str, str]]:
        return {
            "error": {
                "type": self.type,
                "message": self.message,
            }
        }


class ValidationError(APIException):
    """Raised when validation fails."""
    status_code = 400

    def __init__(self, message: str = "Validation error", error_type: Optional[str] = None) -> None:
        self.error_type = error_type or "validation_error"
        super().__init__(message)

    def to_dict(self) -> Dict[str, Dict[str, str]]:
        return {
            "error": {
                "type": self.error_type,
                "message": self.message,
            }
        }


class NotFound(APIException):
    """Raised when a route/resource is not found."""
    status_code = 404

    def __init__(self, message: Optional[str] = None) -> None:
        if message is None:
            message = "Unrecognized request URL."
        super().__init__(message, type="invalid_request_error")


class PermissionDenied(APIException):
    """Raised when permission is denied."""
    status_code = 403

    def __init__(self, message: str = "Permission denied") -> None:
        super().__init__(message, type="permission_denied")


class MethodNotAllowed(APIException):
    """Method not allowed exception."""
    status_code = 405

    def __init__(self, method: str = "", path: str = "") -> None:
        if method and ("not allowed" in method.lower() or "method" in method.lower()):
            message = method
        else:
            message = f"Method '{method}' not allowed for path '{path}'"
        super().__init__(message, type="method_not_allowed")


class Throttled(APIException):
    """Request throttled exception."""
    status_code = 429

    def __init__(self, message: str = "Request throttled", wait: Optional[int] = None) -> None:
        self.wait = wait
        super().__init__(message, type="throttled", status=429)


class AuthenticationFailed(APIException):
    """Authentication failed (401)."""
    status_code = 401

    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message, type="authentication_failed", status=401)
