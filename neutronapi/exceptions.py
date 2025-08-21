"""
Generic NeutronAPI exceptions (like Django's core exceptions).

For module-specific exceptions, import from:
    - neutronapi.api.exceptions (API/HTTP exceptions)
    - neutronapi.db.exceptions (database exceptions)
    - neutronapi.authentication.exceptions (auth exceptions)
    - neutronapi.middleware.exceptions (middleware exceptions)
    - neutronapi.openapi.exceptions (OpenAPI exceptions)
"""


class ImproperlyConfigured(Exception):
    """NeutronAPI is somehow improperly configured."""
    pass


class SuspiciousOperation(Exception):
    """The user did something suspicious."""
    pass


class DisallowedHost(SuspiciousOperation):
    """HTTP_HOST header contains invalid value."""
    pass


class DisallowedRedirect(SuspiciousOperation):
    """Redirect to scheme not in allowed list."""
    pass


class RequestAborted(Exception):
    """Request was aborted."""
    pass


class MiddlewareNotUsed(Exception):
    """This middleware is not used in this server configuration."""
    pass


class FieldError(Exception):
    """Some kind of problem with a model field."""
    pass


class ValidationError(Exception):
    """An error while validating data."""
    pass


class ObjectDoesNotExist(Exception):
    """The requested object does not exist."""
    silent_variable_failure = True


class MultipleObjectsReturned(Exception):
    """The query returned multiple objects when only one was expected."""
    pass

