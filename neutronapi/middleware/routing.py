# core/api/middleware/thalamus.py
import re
import logging
import asyncio
from typing import Callable, Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class RoutingMiddleware:
    """
    Thalamus is the central routing middleware that directs requests based on hostname.
    It also manages application lifecycle events.
    """

    def __init__(
        self,
        default_app: Any,
        static_hosts: Optional[List[str]] = None,
        static_resolver: Optional[Callable] = None,
    ):
        """
        Initialize the Thalamus middleware.

        Args:
            default_app: The default application to route to if no host match is found
            static_hosts: A list of hostnames (exact or with wildcards) to route to the static resolver
            static_resolver: A callable that resolves hostnames to application handlers
        """
        self.default_app = default_app
        self.static_resolver = static_resolver
        self.startup_complete = False

        # Process hosts list into exact matches and patterns
        self.exact_hosts = set()
        self.pattern_hosts = {}

        if static_hosts:
            for host in static_hosts:
                if "*" in host:
                    # Convert wildcard pattern to regex
                    regex_pattern = (
                        "^" + host.replace(".", "\\.").replace("*", ".*") + "$"
                    )
                    self.pattern_hosts[re.compile(regex_pattern)] = True
                else:
                    # Exact hostname match
                    self.exact_hosts.add(host)

    async def _run_startup_handlers(self):
        """Run all registered startup handlers."""
        logger.debug("Running startup handlers")

        # Check if our app or its wrapped apps have startup handlers
        app = self.default_app
        startup_handlers = []

        # Try to find startup handlers at different layers of the application
        if hasattr(app, "on_startup"):
            startup_handlers = app.on_startup
        elif hasattr(app, "app") and hasattr(
            app.app, "on_startup"
        ):  # Check one level down (CORS wrapping)
            startup_handlers = app.app.on_startup
        elif hasattr(app, "default_app") and hasattr(app.default_app, "on_startup"):
            startup_handlers = app.default_app.on_startup

        if startup_handlers:
            logger.debug(f"Found {len(startup_handlers)} startup handlers")

            for i, handler in enumerate(startup_handlers):
                handler_name = getattr(handler, "__name__", f"handler_{i}")
                logger.debug(f"Running startup handler: {handler_name}")
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler()
                    else:
                        handler()
                    logger.debug(f"Completed startup handler: {handler_name}")
                except Exception as e:
                    logger.error(f"Error in startup handler {handler_name}: {e}")
                    import traceback

                    logger.error(traceback.format_exc())
                    raise
        else:
            # Try to import tasks module silently
            try:
                from apps.tasks import initialize_tasks

                logger.debug("Found tasks module, initializing")
                await initialize_tasks()
                logger.debug("Tasks initialization completed")
            except ImportError:
                # No tasks module - this is fine, just continue silently
                logger.debug(
                    "No tasks module found - continuing without background tasks"
                )
            except Exception as e:
                logger.error(f"Error initializing tasks: {e}")
                import traceback

                logger.error(traceback.format_exc())

    async def _run_shutdown_handlers(self):
        """Run all registered shutdown handlers."""
        if hasattr(self.default_app, "on_shutdown"):
            for handler in self.default_app.on_shutdown:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler()
                    else:
                        handler()
                except Exception as e:
                    logger.error(f"Error in shutdown handler: {e}")
                    raise

    async def __call__(self, scope: Dict, receive: Callable, send: Callable, **kwargs):
        """Handle incoming requests and route them to the appropriate app."""
        # Handle lifespan protocol separately
        if scope["type"] == "lifespan":
            message = await receive()

            if message["type"] == "lifespan.startup":
                logger.debug("Application startup")
                try:
                    await self._run_startup_handlers()
                    self.startup_complete = True
                    logger.debug("Application startup completed")
                    await send({"type": "lifespan.startup.complete"})
                except Exception as e:
                    logger.error(f"Startup failed: {e}")
                    import traceback

                    logger.error(traceback.format_exc())
                    await send({"type": "lifespan.startup.failed", "message": str(e)})

            elif message["type"] == "lifespan.shutdown":
                try:
                    await self._run_shutdown_handlers()
                    await send({"type": "lifespan.shutdown.complete"})
                except Exception as e:
                    logger.error(f"Shutdown failed: {e}")
                    await send({"type": "lifespan.shutdown.failed", "message": str(e)})
            return

        # Handle WebSocket connections
        if scope["type"] == "websocket":
            # For now, just pass to the default app
            await self.default_app(scope, receive, send, **kwargs)
            return

        if scope["type"] != "http":
            # Pass through other non-HTTP requests to default app
            await self.default_app(scope, receive, send, **kwargs)
            return

        # Extract the host from headers
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("utf-8", "ignore").split(":")[0]

        handler = None

        # Check if this host should be handled as a static host
        should_handle_static = False

        # Check exact hosts
        if host in self.exact_hosts:
            should_handle_static = True

        # Check pattern hosts
        if not should_handle_static:
            for pattern in self.pattern_hosts:
                if pattern.match(host):
                    should_handle_static = True
                    break

        if should_handle_static:
            if self.static_resolver:
                # Use the provided static resolver
                try:
                    # Check if static_resolver is a class or instance
                    if isinstance(self.static_resolver, type):
                        # It's a class, instantiate it first
                        resolver_instance = self.static_resolver()
                        # Then call the resolve method
                        handler = await resolver_instance.resolve(host)
                    elif hasattr(self.static_resolver, "resolve"):
                        # It's an instance with a resolve method
                        handler = await self.static_resolver.resolve(host)
                    elif callable(self.static_resolver):
                        # It's a function or callable
                        handler = await self.static_resolver(host)
                    else:
                        raise TypeError(
                            f"Invalid resolver type: {type(self.static_resolver)}"
                        )
                except Exception as e:
                    # Capture and display resolver errors
                    logger.error(f"Error in static_resolver for host {host}: {e}")
                    raise

        # Use default app if no static handler found
        handler = handler or self.default_app

        # Allow errors to propagate from the handler for better debugging
        # No catch-all exception handling here to ensure we get detailed error information
        await handler(scope, receive, send, **kwargs)

    def reverse(self, name: str, **kwargs) -> str:
        return self.default_app.reverse(name, **kwargs)
