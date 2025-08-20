from typing import Dict, Optional, Callable, List, Any
import asyncio

from neutronapi.base import API
from neutronapi.middleware.cors import CORS
from neutronapi.middleware.routing import RoutingMiddleware
from neutronapi.middleware.allowed_hosts import AllowedHostsMiddleware
from neutronapi.background import Background, TaskFrequency, TaskPriority


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
        app = Application(apis=[
            HelloAPI(),
            UsersAPI(),
        ])
    """

    def __init__(
        self,
        apis: Optional[List[API]] = None,
        *,
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
        # Convert API list to internal dict mapping
        self.apis = {}
        if apis:
            for api in apis:
                if not hasattr(api, 'resource') or api.resource is None:
                    raise ValueError(f"API {api.__class__.__name__} must have a 'resource' attribute")
                self.apis[api.resource] = api
            
        self.version = version
        
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
                
                # Default 404 for unmatched paths
                await send({
                    "type": "http.response.start",
                    "status": 404,
                    "headers": [[b"content-type", b"text/plain"]],
                })
                await send({
                    "type": "http.response.body",
                    "body": b"Not Found",
                })
        
        # Skip hosts middleware if no allowed_hosts specified (for testing)
        if allowed_hosts:
            hosts_app = AllowedHostsMiddleware(app, allowed_hosts=allowed_hosts)
        else:
            hosts_app = app
        cors_wrapped = CORS(hosts_app, allow_all_origins=cors_allow_all)
        self.app = RoutingMiddleware(
            default_app=cors_wrapped,
            static_hosts=static_hosts,
            static_resolver=static_resolver,
        )

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
    apis: Dict[str, API],
    static_hosts: Optional[List[str]] = None,
    static_resolver: Optional[Callable] = None,
    allowed_hosts: Optional[List[str]] = None,
    version: str = "1.0.0",
    expose_docs: bool = False,  # kept for compatibility; no-op
):
    """Compatibility wrapper that returns an Application instance.

    Docs are not injected automatically; pass your own docs API if desired.
    """
    return Application(
        apis,
        version=version,
        allowed_hosts=allowed_hosts,
        static_hosts=static_hosts,
        static_resolver=static_resolver,
    )
