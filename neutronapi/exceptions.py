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
        self.error_type = error_type
        super().__init__(message)

    def to_dict(self):
        return {
            "error": {
                "type": self.error_type or self.__class__.__name__.lower(),
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
                "If you are trying to retrieve an object, make sure you passed a valid (non-empty) identifier in your code. "
                "Please see https://layerbrain.com/docs."
            )
        super().__init__(message, type="invalid_request_error")


class PermissionDenied(APIException):
    """Raised when permission is denied."""
    status_code = 403

    def __init__(self, message: str = "Permission denied"):
        super().__init__(message)


class AuthenticationFailed(APIException):
    """Raised when authentication fails."""
    status_code = 401

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)


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
        super().__init__(message)


class ResourceError(APIException):
    """Resource error with response payload."""
    status_code = 500

    def __init__(self, response, status_code: int | None = None):
        self.response = response
        self.status_code = status_code or self.status_code

        # Extract message from response if available
        message = "Resource error"
        if isinstance(response, dict):
            if "error" in response:
                error_info = response["error"]
                if isinstance(error_info, dict) and "message" in error_info:
                    message = error_info["message"]
                elif isinstance(error_info, str):
                    message = error_info
            elif "message" in response:
                message = response["message"]

        super().__init__(message, "resource_error", self.status_code)


class DoesNotExist(Exception):
    """Raised when an object does not exist."""
    pass
