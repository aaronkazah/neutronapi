class ValidationError(Exception):
    pass


class AuthenticationFailed(Exception):
    """Raised when authentication fails."""
    pass


class DoesNotExist(Exception):
    """Raised when an object does not exist."""
    pass


class APIException(Exception):
    """Base API exception with status code and type."""
    def __init__(self, message: str, type: str = "api_error", status: int = 500):
        super().__init__(message)
        self.type = type
        self.status = status

