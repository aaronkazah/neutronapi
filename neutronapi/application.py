from typing import Dict, Optional, Callable, List, Any, Union, Protocol, TypeVar, Generic, TYPE_CHECKING
import warnings
import re

if TYPE_CHECKING:
    from neutronapi.base import API


T = TypeVar('T')
RegistryValue = TypeVar('RegistryValue')

from neutronapi.base import API, Response
from neutronapi.api import exceptions
from neutronapi.middleware.cors import CorsMiddleware
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
                # Example: 'services:event_bus': EventBus(), 'services:email': EmailService()
            ],
        )
    """

    def __init__(
        self,
        apis: Optional[Union[Dict[str, API], List[API]]] = None,
        *,
        middlewares: Optional[List[Any]] = None,
        registry: Optional[Dict[str, Any]] = None,
        tasks: Optional[Dict[str, Any]] = None,
        version: str = "1.0.0",
        allowed_hosts: Optional[List[str]] = None,
        static_hosts: Optional[List[str]] = None,
        static_resolver: Optional[Callable] = None,
        cors_allow_all: bool = True,
    ) -> None:
        """
        Create a new ASGI application with dependency injection support.

        Args:
            apis: List or dict of API instances. Each API must have a 'resource' attribute
                  that defines its base path (e.g., "/v1/users"). APIs are registered
                  in the order they appear in the list.
            middlewares: List of middleware instances to apply to requests
            registry: Dict of items for universal dependency injection. Keys must
                     follow 'namespace:name' format (e.g., 'utils:logger', 'services:email')
            tasks: Optional background tasks configuration
            version: Application version string
            allowed_hosts: List of allowed host names for security
            static_hosts: Static file hosting configuration
            static_resolver: Custom static file resolver
            cors_allow_all: Whether to allow all CORS origins (default: True)

        Example:
            >>> app = Application(
            ...     apis=[
            ...         UsersAPI(),      # resource = "/v1/users"
            ...         ProductsAPI(),   # resource = "/v1/products"
            ...     ],
            ...     registry={
            ...         'utils:logger': Logger(),
            ...         'utils:cache': RedisCache(),
            ...         'services:email': EmailService(),
            ...     },
            ... )
            >>> 
            >>> # In your API methods:
            >>> logger = self.registry.get('utils:logger')
            >>> email = self.registry.get('services:email')
        """
        # Convert provided APIs into two mappings: name-based and resource-based
        from neutronapi.base import API
        self.apis: Dict[str, 'API'] = {}  # name -> api (for reverse lookups)
        self._resource_apis: Dict[str, 'API'] = {}  # resource -> api (for routing)
        
        if apis:
            if isinstance(apis, dict):
                # Use the provided names from the dict
                for name, api in apis.items():
                    if not hasattr(api, 'resource'):
                        raise ValueError(f"API {api.__class__.__name__} must have a 'resource' attribute")
                    resource = getattr(api, 'resource', None)
                    if resource is None:
                        raise ValueError(f"API {api.__class__.__name__} must define a non-null 'resource'")
                    self.apis[name] = api
                    self._resource_apis[resource] = api
            else:
                # For list[API], use the API name as the key for reverse lookups
                for api in apis:
                    if not hasattr(api, 'resource'):
                        raise ValueError(f"API {api.__class__.__name__} must have a 'resource' attribute")
                    resource = getattr(api, 'resource', None)
                    if resource is None:
                        raise ValueError(f"API {api.__class__.__name__} must define a non-null 'resource'")
                    
                    # Require explicit 'name' attribute for reverse lookups
                    if not hasattr(api, 'name') or not api.name:
                        raise ValueError(f"API {api.__class__.__name__} must have a 'name' attribute for reverse lookups")
                    
                    self.apis[api.name] = api
                    self._resource_apis[resource] = api
        
        # Validate no duplicate route names across all APIs
        self._validate_unique_route_names()

        self.version = version

        # Initialize registry for universal dependency injection
        self.registry: Dict[str, Any] = {}
        
        # Handle registry parameter - validate namespace:name format
        if registry:
            for key, value in registry.items():
                self._validate_registry_key(key)
                if key in self.registry:
                    raise ValueError(f"Duplicate registry key: '{key}'")
                self.registry[key] = value
        
        # Assign registry to APIs
        for api in self.apis.values():
            setattr(api, 'registry', self.registry)

        # Simple handler that routes to APIs
        async def app(scope, receive, send):
            if scope["type"] == "http":
                path = scope.get("path", "/")

                # Check if path matches any API exactly
                if path in self._resource_apis:
                    api = self._resource_apis[path]
                    await api.handle(scope, receive, send)
                    return

                # Check if path starts with any API prefix
                for api_path, api in self._resource_apis.items():
                    if path.startswith(api_path):
                        await api.handle(scope, receive, send)
                        return

                # Default 404 for unmatched paths - return consistent JSON error
                err = exceptions.NotFound().to_dict()
                resp = Response(body=err, status_code=404)
                await resp(scope, receive, send)

        # Set lifecycle hooks on app function so RoutingMiddleware can find them
        app.on_startup = []
        app.on_shutdown = []

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
                # Provide shared registry if middleware wants it
                if hasattr(mw, 'set_registry') and callable(getattr(mw, 'set_registry')):
                    mw.set_registry(self.registry)
                elif hasattr(mw, 'registry'):
                    try:
                        setattr(mw, 'registry', self.registry)
                    except Exception:
                        pass
                composed = mw
            self.app = composed
        else:
            # Legacy minimal wrapping
            hosts_app = AllowedHostsMiddleware(base_router,
                                               allowed_hosts=allowed_hosts) if allowed_hosts else base_router
            self.app = CorsMiddleware(hosts_app, allow_all_origins=cors_allow_all)

        # Expose lifecycle hooks on Application instance for compatibility
        # (handlers are already set on the app function above)
        self.on_startup = app.on_startup
        self.on_shutdown = app.on_shutdown

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

            app.on_startup.append(_start_background)
            app.on_shutdown.append(_stop_background)

    def _validate_registry_key(self, key: str) -> None:
        """Validate registry key follows namespace:name format.
        
        Args:
            key: Registry key to validate
            
        Raises:
            ValueError: If key format is invalid
            
        Example:
            Valid: 'services:email', 'utils:logger', 'modules:auth'
            Invalid: 'email', 'services:', ':logger', 'utils:my-logger'
        """
        if not isinstance(key, str):
            raise ValueError(f"Registry key must be string, got {type(key).__name__}")
        
        if ':' not in key:
            raise ValueError(
                f"Registry key '{key}' must follow 'namespace:name' format. "
                f"Example: 'services:email', 'utils:logger'"
            )
        
        namespace, name = key.split(':', 1)
        if not namespace or not name:
            raise ValueError(
                f"Registry key '{key}' must have both namespace and name. "
                f"Got namespace='{namespace}', name='{name}'"
            )
        
        # Validate format - alphanumeric + underscore only
        if not re.match(r'^[a-zA-Z0-9_]+:[a-zA-Z0-9_]+$', key):
            raise ValueError(
                f"Registry key '{key}' contains invalid characters. "
                f"Use only letters, numbers, underscores. Example: 'utils:my_logger'"
            )
    
    def register(self, key: str, item: Any) -> None:
        """Register an item in the registry for dependency injection.
        
        Args:
            key: Registry key in 'namespace:name' format (e.g., 'utils:logger')
            item: The item to register. Can be any object.
            
        Raises:
            ValueError: If key format is invalid or key already exists
            
        Example:
            >>> app = Application()
            >>> logger = Logger()
            >>> app.register('utils:logger', logger)
            >>> # Later in your API:
            >>> logger = self.registry.get('utils:logger')
        """
        self._validate_registry_key(key)
        
        if key in self.registry:
            raise ValueError(
                f"Registry key '{key}' already exists. "
                f"Use a different key or remove the existing registration first."
            )
        
        self.registry[key] = item
        
        # Re-inject registry into existing APIs
        for api in self.apis.values():
            setattr(api, 'registry', self.registry)
    
    def get_registry_item(self, key: str, default: Optional[T] = None) -> Optional[T]:
        """Get an item from the registry with type preservation.
        
        Args:
            key: Registry key in 'namespace:name' format
            default: Default value if key not found
            
        Returns:
            The registered item or default value
            
        Example:
            >>> logger = app.get_registry_item('utils:logger')
            >>> cache = app.get_registry_item('utils:cache', default=DummyCache())
        """
        return self.registry.get(key, default)
    
    def has_registry_item(self, key: str) -> bool:
        """Check if an item exists in the registry.
        
        Args:
            key: Registry key to check
            
        Returns:
            True if key exists in registry, False otherwise
        """
        return key in self.registry
    
    def list_registry_keys(self, namespace: Optional[str] = None) -> List[str]:
        """List all registry keys, optionally filtered by namespace.
        
        Args:
            namespace: Optional namespace to filter by (e.g., 'utils', 'services')
            
        Returns:
            List of registry keys
            
        Example:
            >>> app.list_registry_keys()  # ['services:email', 'utils:logger']
            >>> app.list_registry_keys('utils')  # ['utils:logger']
        """
        if namespace is None:
            return list(self.registry.keys())
        
        prefix = f"{namespace}:"
        return [key for key in self.registry.keys() if key.startswith(prefix)]

    def _validate_unique_route_names(self) -> None:
        """Validate that there are no duplicate route names across all APIs.
        
        Route names are in the format "api_name:endpoint_name".
        
        Raises:
            ValueError: If duplicate route names are found
        """
        seen_routes = {}  # route_name -> api_name
        
        for api_name, api in self.apis.items():
            # Get all route names from this API
            for route_tuple in api.routes:
                # Route tuple structure: (pattern, handler, methods, permissions, throttles, route_name, original_path, ...)
                if len(route_tuple) >= 6:
                    route_name = route_tuple[5]  # route_name is at index 5
                    if route_name:  # Only check named routes
                        full_route_name = f"{api_name}:{route_name}"
                        
                        if full_route_name in seen_routes:
                            raise ValueError(
                                f"Duplicate route name '{full_route_name}' found. "
                                f"Route names must be unique across all APIs. "
                                f"Previously defined in API '{seen_routes[full_route_name]}', "
                                f"now found again in API '{api_name}'."
                            )
                        
                        seen_routes[full_route_name] = api_name

    def reverse(self, name: str, **kwargs) -> str:
        """Reverse URL lookup for a named route across all registered APIs.
        
        Args:
            name: Route name in format "api_name:endpoint_name"
            **kwargs: Parameters to substitute in the URL
            
        Returns:
            The reversed URL string
            
        Raises:
            ValueError: If API not found or invalid name format
            
        Example:
            >>> app = Application(apis={"users": users_api})
            >>> url = app.reverse("users:detail", user_id=123)
            >>> # Returns: "/users/123"
        """
        if ":" not in name:
            raise ValueError(
                f"Route name '{name}' must be in format 'api_name:endpoint_name'. "
                f"Example: 'users:detail'"
            )
        
        api_name, endpoint_name = name.split(":", 1)
        if api_name not in self.apis:
            raise ValueError(f"API '{api_name}' not found.")
        
        return self.apis[api_name].reverse(endpoint_name, **kwargs)

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
