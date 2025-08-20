from typing import Dict, Optional, Callable, List, Any, Union
import warnings

from neutronapi.base import API, Response
from neutronapi import exceptions
from neutronapi.middleware.cors import CORS
from neutronapi.middleware.routing import RoutingMiddleware
from neutronapi.middleware.allowed_hosts import AllowedHostsMiddleware


class Application:
    """ASGI application that composes APIs + middleware + optional background tasks.

    Example:
        from neutronapi.application import Application
        from neutronapi.base import API

        class HelloAPI(API):
            resource = "/v1/hello"

            @API.endpoint("/", methods=["GET"])
            async def get(self, scope, receive, send, **kwargs):
                return await self.response({"message": "Hello World"})

        class UsersAPI(API):
            resource = "/v1/users"

            @API.endpoint("/", methods=["GET"])
            async def list_users(self, scope, receive, send, **kwargs):
                return await self.response({"users": []})

        # Clean array-based syntax - no redundancy!
        # Middlewares and services are instances only.
        from neutronapi.middleware.compression import CompressionMiddleware
        from neutronapi.middleware.allowed_hosts import AllowedHostsMiddleware

        app = Application(
            apis=[
                HelloAPI(),
                UsersAPI(),
            ],
            middlewares=[
                AllowedHostsMiddleware(allowed_hosts=["example.com", "*.example.com"]),
                CompressionMiddleware(minimum_size=512),
            ],
            services=[
                # Example: EventBus(id="event_bus"), EmailService(id="email")
            ],
        )
    """

    def __init__(
        self,
        apis: Optional[Union[Dict[str, API], List[API]]] = None,
        *,
        middlewares: Optional[List[Any]] = None,
        services: Optional[Union[List[Any], Dict[str, Any]]] = None,
        tasks: Optional[Dict[str, Any]] = None,
        version: str = "1.0.0",
        allowed_hosts: Optional[List[str]] = None,
        static_hosts: Optional[List[str]] = None,
        static_resolver: Optional[Callable] = None,
        cors_allow_all: bool = True,
    ) -> None:
        """
        Create a new ASGI application.

        Args:
            apis: List of API instances. Each API must have a 'resource' attribute
                  that defines its base path (e.g., "/v1/users"). APIs are registered
                  in the order they appear in the list.
            tasks: Optional background tasks configuration
            version: Application version string
            allowed_hosts: List of allowed host names for security
            static_hosts: Static file hosting configuration
            static_resolver: Custom static file resolver
            cors_allow_all: Whether to allow all CORS origins (default: True)

        Example:
            app = Application(apis=[
                UsersAPI(),      # resource = "/v1/users"
                ProductsAPI(),   # resource = "/v1/products"
            ])
        """
        # Convert provided APIs (list or dict) into internal {resource: api} mapping
        self.apis: Dict[str, API] = {}
        if apis:
            # Support both list[API] and dict[str, API]
            api_iterable = apis.values() if isinstance(apis, dict) else apis
            for api in api_iterable:
                if not hasattr(api, 'resource'):
                    raise ValueError(f"API {api.__class__.__name__} must have a 'resource' attribute")
                resource = getattr(api, 'resource', None)
                if resource is None:
                    raise ValueError(f"API {api.__class__.__name__} must define a non-null 'resource'")
                self.apis[resource] = api

        self.version = version

        # Normalize services (input: list or dict of instances) → dict keyed by id
        self.services: Dict[str, Any] = {}
        if services:
            if isinstance(services, dict):
                self.services = dict(services)
            else:
                for svc in services:
                    sid = getattr(svc, 'id', None)
                    if not sid:
                        raise ValueError("Service instances must have an 'id' attribute")
                    if sid in self.services:
                        raise ValueError(f"Duplicate service id: {sid}")
                    self.services[sid] = svc
            # Propagate container to each service instance
            for svc in self.services.values():
                if hasattr(svc, 'set_services') and callable(getattr(svc, 'set_services')):
                    svc.set_services(self.services)
                else:
                    try:
                        setattr(svc, 'services', self.services)
                    except Exception:
                        pass
        # Assign services to APIs
        for api in self.apis.values():
            setattr(api, 'services', self.services)

        # Simple handler that routes to APIs
        async def app(scope, receive, send):
            if scope["type"] == "http":
                path = scope.get("path", "/")

                # Check if path matches any API exactly
                if path in self.apis:
                    api = self.apis[path]
                    await api.handle(scope, receive, send)
                    return

                # Check if path starts with any API prefix
                for api_path, api in self.apis.items():
                    if path.startswith(api_path):
                        await api.handle(scope, receive, send)
                        return

                # Default 404 for unmatched paths - return consistent JSON error
                err = exceptions.NotFound().to_dict()
                resp = Response(body=err, status_code=404)
                await resp(scope, receive, send)

        # Build base router app
        base_router = RoutingMiddleware(
            default_app=app,
            static_hosts=static_hosts,
            static_resolver=static_resolver,
        )

        # Compose provided middlewares (instances only), else fallback to legacy allowed_hosts + CORS
        if middlewares:
            composed = base_router
            # Middlewares are declared outermost-first; apply in reverse to wrap
            for mw in reversed(middlewares):
                # Late-bind the inner app
                if hasattr(mw, 'app'):
                    mw.app = composed
                if hasattr(mw, 'router'):
                    mw.router = composed
                # Provide shared services if middleware wants it
                if hasattr(mw, 'set_services') and callable(getattr(mw, 'set_services')):
                    mw.set_services(self.services)
                elif hasattr(mw, 'services'):
                    try:
                        setattr(mw, 'services', self.services)
                    except Exception:
                        pass
                composed = mw
            self.app = composed
        else:
            # Legacy minimal wrapping
            hosts_app = AllowedHostsMiddleware(base_router,
                                               allowed_hosts=allowed_hosts) if allowed_hosts else base_router
            self.app = CORS(hosts_app, allow_all_origins=cors_allow_all)

        # lifecycle hooks
        self.app.on_startup = []
        self.app.on_shutdown = []

        # Expose lifecycle hooks on Application instance for compatibility
        self.on_startup = self.app.on_startup
        self.on_shutdown = self.app.on_shutdown

        # Handle tasks dict - clean API-like pattern
        if tasks:
            from neutronapi.background import Background
            self.background = Background()

            # Register all tasks
            for name, task in tasks.items():
                self.background.register_task(task)

            async def _start_background():
                await self.background.start()

            async def _stop_background():
                await self.background.stop()

            self.app.on_startup.append(_start_background)
            self.app.on_shutdown.append(_stop_background)

    async def __call__(self, scope, receive, send, **kwargs):
        return await self.app(scope, receive, send, **kwargs)


def create_application(
    apis: Union[Dict[str, API], List[API]],
    static_hosts: Optional[List[str]] = None,
    static_resolver: Optional[Callable] = None,
    allowed_hosts: Optional[List[str]] = None,
    version: str = "1.0.0",
    expose_docs: bool = False,  # kept for compatibility; no-op
):
    """Deprecated compatibility wrapper for creating an Application.

    Deprecated in 0.1.3: use Application(apis=[...]) or Application(apis={...}) directly.
    Docs are not injected automatically; pass your own docs API if desired.
    """
    warnings.warn(
        "create_application is deprecated as of 0.1.3; "
        "construct Application directly with list or dict of APIs.",
        DeprecationWarning,
        stacklevel=2,
    )
    return Application(
        apis=apis,
        version=version,
        allowed_hosts=allowed_hosts,
        static_hosts=static_hosts,
        static_resolver=static_resolver,
    )
