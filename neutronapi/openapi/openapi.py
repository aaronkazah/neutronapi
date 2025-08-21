"""
OpenAPI specification generator for the API framework.

This module provides functionality to automatically generate OpenAPI 3.0 specifications
from API instances and create_application configurations, similar to how Stripe API
provides comprehensive documentation.
"""

import json
import re
import os
import fnmatch
from typing import Dict, List, Any, Optional
import os

from neutronapi.base import API
from neutronapi.middleware.routing import RoutingMiddleware


class OpenAPIGenerator:
    """
    Generates OpenAPI 3.0 specifications from API instances.

    Supports automatic generation from:
    - Individual API instances
    - Router with multiple APIs
    - Full application created with create_application()
    """

    def __init__(
        self,
        title: str = "API Documentation",
        description: str = "Auto-generated API documentation",
        version: str = "1.0.0",
        servers: Optional[List[Dict[str, str]]] = None,
        contact: Optional[Dict[str, str]] = None,
        license_info: Optional[Dict[str, str]] = None,
        override_router_version: bool = False,
    ):
        self.title = title
        self.description = description
        self.version = version
        self.override_router_version = override_router_version
        self.servers = servers or [
            {"url": "https://api.example.com", "description": "Production server"}
        ]
        self.contact = contact
        self.license_info = license_info

        self.spec = {
            "openapi": "3.0.3",
            "info": {
                "title": self.title,
                "description": self.description,
                "version": self.version,
            },
            "servers": self.servers,
            "paths": {},
            "components": {
                "schemas": {},
                "securitySchemes": {},
                "responses": {},
                "parameters": {},
            },
            "tags": [],
            "security": [],
        }

        if self.contact:
            self.spec["info"]["contact"] = self.contact
        if self.license_info:
            self.spec["info"]["license"] = self.license_info

    async def generate_from_application(self, app: RoutingMiddleware) -> Dict[str, Any]:
        """
        Generate OpenAPI spec from a complete application created with create_application().

        Args:
            app: Thalamus application instance

        Returns:
            Complete OpenAPI 3.0 specification
        """
        # Extract the router from the middleware chain
        router = self._extract_router_from_app(app)
        if router:
            return await self.generate_from_router(router)
        else:
            raise ValueError("Could not extract router from application")

    async def generate_from_router(self, router) -> Dict[str, Any]:
        """
        Generate OpenAPI spec from a Router with multiple APIs.

        Args:
            router: Router instance containing multiple APIs

        Returns:
            Complete OpenAPI 3.0 specification
        """
        # Use the router's version if available, unless generator explicitly overrides
        if (
            hasattr(router, "version")
            and router.version
            and not self.override_router_version
        ):
            self.spec["info"]["version"] = router.version

        for api_name, api in router.apis.items():
            await self._process_api(api)

        return self.spec

    async def generate_from_api(self, api: API) -> Dict[str, Any]:
        """
        Generate OpenAPI spec from a single API instance.

        Args:
            api: API instance

        Returns:
            Complete OpenAPI 3.0 specification
        """
        await self._process_api(api)
        return self.spec

    async def generate(self, *, source) -> Dict[str, Any]:
        """
        Generate OpenAPI spec from Application, API, or dict of APIs.
        
        Args:
            source: Application instance, API instance, or dict of APIs
            
        Returns:
            Complete OpenAPI 3.0 specification
        """
        from neutronapi.application import Application
        from neutronapi.base import API
        
        if isinstance(source, Application):
            # Extract APIs from Application
            if hasattr(source, 'apis') and source.apis:
                for api in source.apis.values():
                    await self._process_api(api)
            return self.spec
        elif isinstance(source, API):
            # Single API
            await self._process_api(source)
            return self.spec
        elif isinstance(source, dict):
            # Dict of APIs
            for api in source.values():
                if isinstance(api, API):
                    await self._process_api(api)
            return self.spec
        else:
            raise ValueError("Source must be Application, API, or dict of APIs")

    def _extract_router_from_app(self, app: RoutingMiddleware):
        """Extract the Router from the middleware chain."""
        current = app.default_app

        # Navigate through middleware layers to find the Router
        while current is not None:
            # Check if current has router-like attributes
            if hasattr(current, 'apis'):
                return current

            # Try different attribute names used by middleware
            if hasattr(current, "app") and current.app is not None:
                current = current.app
            elif hasattr(current, "router") and current.router is not None:
                current = current.router
            elif hasattr(current, "default_app") and current.default_app is not None:
                current = current.default_app
            else:
                break

        return None

    async def _process_api(self, api: API) -> None:
        """Process a single API instance and add its routes to the spec."""
        # Skip hidden APIs entirely
        if getattr(api, "hidden", False):
            return

        # Add API-level tags
        if api.tags:
            for tag in api.tags:
                if tag not in [t["name"] for t in self.spec["tags"]]:
                    self.spec["tags"].append(
                        {"name": tag, "description": f"Operations for {tag}"}
                    )
        elif api.name:
            tag_name = api.name.title()
            if tag_name not in [t["name"] for t in self.spec["tags"]]:
                self.spec["tags"].append(
                    {
                        "name": tag_name,
                        "description": api.description or f"Operations for {api.name}",
                    }
                )

        # Add security schemes if authentication is required
        if api.authentication_class:
            self._add_security_scheme(api.authentication_class)

        # Process all routes
        for route_info in api.routes:
            (
                pattern,
                handler,
                methods,
                permission_classes,
                throttle_classes,
                name,
                original_path,
                skip_body_parsing,
            ) = route_info

            # Skip websocket routes for now
            if methods == ["WEBSOCKET"]:
                continue

            # Check if endpoint should be included in docs
            if not self._should_include_endpoint(handler, original_path, methods):
                continue

            await self._process_route(
                api,
                original_path,
                methods,
                handler,
                name,
                permission_classes,
                throttle_classes,
            )

    def _should_include_endpoint(
        self, handler: callable, path: str, methods: List[str]
    ) -> bool:
        """Check if an endpoint should be included in documentation."""
        # Check endpoint-level include_in_docs setting
        endpoint_metadata = getattr(handler, "_endpoint", None)
        if endpoint_metadata and not endpoint_metadata.include_in_docs:
            return False

        # Check environment-based exclusion patterns
        exclude_patterns = os.environ.get("API_DOCS_EXCLUDE_PATTERNS", "").split(",")
        exclude_patterns = [p.strip() for p in exclude_patterns if p.strip()]

        for pattern in exclude_patterns:
            if fnmatch.fnmatch(path, pattern):
                return False

        # Check if internal endpoints should be included
        include_internal = (
            os.environ.get("INCLUDE_INTERNAL_ENDPOINTS", "False").lower() == "True"
        )
        if not include_internal:
            # Default internal patterns to exclude
            internal_patterns = ["/internal/*", "/debug/*", "/_*"]
            for pattern in internal_patterns:
                if fnmatch.fnmatch(path, pattern):
                    return False

        return True

    async def _process_route(
        self,
        api: API,
        path: str,
        methods: List[str],
        handler: callable,
        name: Optional[str],
        permission_classes: List[Any],
        throttle_classes: List[Any],
    ) -> None:
        """Process a single route and add it to the OpenAPI spec."""
        # Convert path parameters to OpenAPI format
        openapi_path = self._convert_path_to_openapi(path)

        if openapi_path not in self.spec["paths"]:
            self.spec["paths"][openapi_path] = {}

        for method in methods:
            method_lower = method.lower()
            if method_lower == "websocket":
                continue

            operation = await self._create_operation(
                api, handler, method, name, permission_classes, throttle_classes
            )

            self.spec["paths"][openapi_path][method_lower] = operation

    async def _create_operation(
        self,
        api: API,
        handler: callable,
        method: str,
        name: Optional[str],
        permission_classes: List[Any],
        throttle_classes: List[Any],
    ) -> Dict[str, Any]:
        """Create an OpenAPI operation object."""
        # Check if handler has enhanced endpoint metadata
        endpoint_metadata = getattr(handler, "_endpoint", None)

        operation = {
            "summary": self._get_summary(handler, method, name, endpoint_metadata),
            "description": self._get_description(handler, api, endpoint_metadata),
            "operationId": self._generate_operation_id(api, handler, method, name),
            "responses": self._get_responses(api, handler, method, endpoint_metadata),
        }

        # Add tags from endpoint metadata or API
        tags = self._get_tags(api, endpoint_metadata)
        if tags:
            operation["tags"] = tags

        # Add parameters from endpoint metadata or auto-generate
        parameters = self._get_parameters(api, method, endpoint_metadata)
        if parameters:
            operation["parameters"] = parameters

        # Add request body for POST/PUT/PATCH
        if method.upper() in ["POST", "PUT", "PATCH"]:
            request_body = self._get_request_body(api, method, endpoint_metadata)
            if request_body:
                operation["requestBody"] = request_body

        # Mark as deprecated if specified
        if endpoint_metadata and endpoint_metadata.deprecated:
            operation["deprecated"] = True

        # Add tags
        if api.tags:
            operation["tags"] = api.tags
        elif api.name:
            operation["tags"] = [api.name.title()]

        # Add parameters
        parameters = self._generate_parameters(api, method)
        if parameters:
            operation["parameters"] = parameters

        # Add request body for POST/PUT/PATCH
        if method.upper() in ["POST", "PUT", "PATCH"]:
            request_body = self._generate_request_body(api, handler)
            if request_body:
                operation["requestBody"] = request_body

        # Add security if authentication is required
        if api.authentication_class or permission_classes:
            operation["security"] = self._generate_security_requirements(
                api.authentication_class
            )

        return operation

    def _get_summary(
        self, handler: callable, method: str, name: Optional[str], endpoint_metadata
    ) -> str:
        """Get summary from endpoint metadata or generate one."""
        if endpoint_metadata and endpoint_metadata.summary:
            return endpoint_metadata.summary
        return self._generate_summary(handler, method, name)

    def _get_description(self, handler: callable, api: API, endpoint_metadata) -> str:
        """Get description from endpoint metadata, docstring, or generate one."""
        if endpoint_metadata and endpoint_metadata.description:
            return endpoint_metadata.description
        return self._generate_description(handler, api)

    def _get_tags(self, api: API, endpoint_metadata) -> Optional[List[str]]:
        """Get tags from endpoint metadata or API."""
        if endpoint_metadata and endpoint_metadata.tags:
            return endpoint_metadata.tags
        elif api.tags:
            return api.tags
        elif api.name:
            return [api.name.title()]
        return None

    def _get_parameters(
        self, api: API, method: str, endpoint_metadata
    ) -> Optional[List[Dict[str, Any]]]:
        """Get parameters from endpoint metadata or auto-generate."""
        if endpoint_metadata and endpoint_metadata.parameters:
            return endpoint_metadata.parameters
        return self._generate_parameters(api, method)

    def _get_responses(
        self, api: API, handler: callable, method: str, endpoint_metadata
    ) -> Dict[str, Any]:
        """Get responses from endpoint metadata or auto-generate."""
        if endpoint_metadata and endpoint_metadata.responses:
            # Use custom responses but ensure 200 response exists
            responses = endpoint_metadata.responses.copy()
            if 200 not in responses:
                # Add default 200 response
                schema = endpoint_metadata.response_schema or self._get_response_schema(
                    api, handler, method
                )
                responses[200] = {
                    "description": "Successful response",
                    "content": {"application/json": {"schema": schema}},
                }
            # Convert int keys to strings for OpenAPI
            return {
                str(k): (
                    v
                    if isinstance(v, dict) and "description" in v
                    else {
                        "description": f"HTTP {k} response",
                        "content": {"application/json": {"schema": v}},
                    }
                )
                for k, v in responses.items()
            }
        return self._generate_responses(api, handler, method)

    def _get_request_body(
        self, api: API, method: str, endpoint_metadata
    ) -> Optional[Dict[str, Any]]:
        """Get request body from endpoint metadata or auto-generate."""
        if endpoint_metadata and endpoint_metadata.request_schema:
            return {
                "required": True,
                "content": {
                    "application/json": {"schema": endpoint_metadata.request_schema}
                },
            }
        return self._generate_request_body(api, None)

    def _convert_path_to_openapi(self, path: str) -> str:
        """Convert path parameters to OpenAPI format."""

        # Convert <str:id> to {id}, <int:count> to {count}, etc.
        def replace_param(match):
            param_type = match.group(1)
            param_name = match.group(2)
            return f"{{{param_name}}}"

        return re.sub(r"<(\w+):(\w+)>", replace_param, path)

    def _generate_summary(
        self, handler: callable, method: str, name: Optional[str]
    ) -> str:
        """Generate a summary for the operation."""
        if hasattr(handler, "__doc__") and handler.__doc__:
            # Use first line of docstring
            return handler.__doc__.strip().split("\n")[0]

        if name:
            return f"{method.title()} {name}"

        return f"{method.title()} operation"

    def _generate_description(self, handler: callable, api: API) -> str:
        """Generate a description for the operation."""
        if hasattr(handler, "__doc__") and handler.__doc__:
            return handler.__doc__.strip()

        return f"Operation provided by {api.__class__.__name__}"

    def _generate_operation_id(
        self, api: API, handler: callable, method: str, name: Optional[str]
    ) -> str:
        """Generate a unique operation ID."""
        api_name = api.name or api.__class__.__name__.replace("API", "").lower()
        operation_name = name or handler.__name__
        return f"{api_name}_{operation_name}_{method.lower()}"

    def _generate_responses(
        self, api: API, handler: callable, method: str
    ) -> Dict[str, Any]:
        """Generate response definitions."""
        responses = {
            "200": {
                "description": "Successful response",
                "content": {
                    "application/json": {
                        "schema": self._get_response_schema(api, handler, method)
                    }
                },
            }
        }

        # Add common error responses
        if api.authentication_class:
            responses["401"] = {
                "description": "Authentication required",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Error"}
                    }
                },
            }

        responses["404"] = {
            "description": "Resource not found",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
            },
        }

        responses["500"] = {
            "description": "Internal server error",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
            },
        }

        # Add error schema to components
        self.spec["components"]["schemas"]["Error"] = {
            "type": "object",
            "properties": {
                "error": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "message": {"type": "string"},
                    },
                    "required": ["type", "message"],
                }
            },
            "required": ["error"],
        }

        return responses

    def _get_response_schema(
        self, api: API, handler: callable, method: str
    ) -> Dict[str, Any]:
        """Get the response schema for an operation."""
        # Check if it's a list operation first
        if handler.__name__ == "list" or (
            method.upper() == "GET" and not hasattr(handler, "__self__")
        ):
            if hasattr(api, "list_response_schema") and api.list_response_schema:
                return api.list_response_schema
            return self._generate_list_schema(api)

        # Check if API has custom response schema for non-list operations
        if hasattr(api, "response_schema") and api.response_schema:
            return api.response_schema

        # Default object response
        return {
            "type": "object",
            "properties": {"id": {"type": "string"}, "object": {"type": "string"}},
        }

    def _generate_list_schema(self, api: API = None) -> Dict[str, Any]:
        """Generate a standard list response schema."""
        # Use API's list_response_schema if available, otherwise response_schema
        item_schema = {"type": "object"}
        if api:
            if hasattr(api, "list_response_schema") and api.list_response_schema:
                item_schema = api.list_response_schema
            elif hasattr(api, "response_schema") and api.response_schema:
                item_schema = api.response_schema

        return {
            "type": "object",
            "properties": {
                "object": {"type": "string", "example": "list"},
                "data": {"type": "array", "items": item_schema},
                "page": {"type": "integer"},
                "page_size": {"type": "integer"},
                "count": {"type": "integer"},
                "num_pages": {"type": "integer"},
                "has_more": {"type": "boolean"},
            },
            "required": ["object", "data"],
        }

    def _generate_parameters(self, api: API, method: str) -> List[Dict[str, Any]]:
        """Generate parameters for the operation."""
        parameters = []

        # Add pagination parameters for GET requests
        if method.upper() == "GET":
            parameters.extend(
                [
                    {
                        "name": "page",
                        "in": "query",
                        "description": "Page number",
                        "required": False,
                        "schema": {"type": "integer", "default": 1, "minimum": 1},
                    },
                    {
                        "name": "page_size",
                        "in": "query",
                        "description": "Number of items per page",
                        "required": False,
                        "schema": {
                            "type": "integer",
                            "default": api.page_size,
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                    {
                        "name": "ordering",
                        "in": "query",
                        "description": "Field to order by",
                        "required": False,
                        "schema": {"type": "string"},
                    },
                ]
            )

        return parameters

    def _generate_request_body(
        self, api: API, handler: callable
    ) -> Optional[Dict[str, Any]]:
        """Generate request body definition."""
        if hasattr(api, "request_schema") and api.request_schema:
            return {
                "required": True,
                "content": {"application/json": {"schema": api.request_schema}},
            }

        # Default request body
        return {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object", "additionalProperties": True}
                }
            },
        }

    def _add_security_scheme(self, auth_class: Any) -> None:
        """Add security scheme based on authentication class."""
        # Basic JWT/Bearer token scheme
        if "JWT" in auth_class.__name__ or "Token" in auth_class.__name__:
            self.spec["components"]["securitySchemes"]["bearerAuth"] = {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        # API Key scheme
        elif "APIKey" in auth_class.__name__:
            self.spec["components"]["securitySchemes"]["apiKey"] = {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
            }

    def _generate_security_requirements(
        self, auth_class: Any
    ) -> List[Dict[str, List[str]]]:
        """Generate security requirements for an operation."""
        if not auth_class:
            return []

        if "JWT" in auth_class.__name__ or "Token" in auth_class.__name__:
            return [{"bearerAuth": []}]
        elif "APIKey" in auth_class.__name__:
            return [{"apiKey": []}]

        return []

    def to_json(self, indent: int = 2) -> str:
        """Convert the specification to JSON string."""
        return json.dumps(self.spec, indent=indent, ensure_ascii=False)

    def to_dict(self) -> Dict[str, Any]:
        """Get the specification as a dictionary."""
        return self.spec

    def _should_include_endpoint(
        self, handler: callable, path: str, methods: List[str]
    ) -> bool:
        """
        Determine if an endpoint should be included in the documentation.

        Args:
            handler: The endpoint handler function
            path: The endpoint path
            methods: List of HTTP methods

        Returns:
            True if endpoint should be included, False otherwise
        """
        # Check endpoint-level include_in_docs flag
        if hasattr(handler, "_endpoint"):
            metadata = handler._endpoint
            if not getattr(metadata, "include_in_docs", True):
                return False

        # Check global exclusion patterns (environment-based filtering)
        exclude_patterns = self._get_exclusion_patterns()
        for pattern in exclude_patterns:
            if self._matches_pattern(path, pattern):
                return False

        # Check for internal/debug endpoints (common patterns to exclude)
        internal_patterns = [
            "/internal/*",
            "/debug/*",
            "/_*",
            "/health*",  # Often excluded from public docs
        ]

        # Allow override via environment variable
        if os.getenv("INCLUDE_INTERNAL_ENDPOINTS", "").lower() != "True":
            for pattern in internal_patterns:
                if self._matches_pattern(path, pattern):
                    return False

        return True

    def _get_exclusion_patterns(self) -> List[str]:
        """Get list of path patterns to exclude from documentation."""
        patterns = []

        # Environment variable for custom exclusions
        env_excludes = os.getenv("API_DOCS_EXCLUDE_PATTERNS", "")
        if env_excludes:
            patterns.extend([p.strip() for p in env_excludes.split(",") if p.strip()])

        return patterns

    def _matches_pattern(self, path: str, pattern: str) -> bool:
        """Check if a path matches a glob-style pattern."""
        import fnmatch

        return fnmatch.fnmatch(path, pattern)


async def generate_openapi_from_application(
    app: RoutingMiddleware,
    title: str = "API Documentation",
    description: str = "Auto-generated API documentation",
    version: str = "1.0.0",
    **kwargs,
) -> Dict[str, Any]:
    """
    Convenience function to generate OpenAPI spec from a create_application() result.

    Args:
        app: Application created with create_application()
        title: API title
        description: API description
        version: API version (overrides router's version)
        **kwargs: Additional arguments for OpenAPIGenerator

    Returns:
        OpenAPI 3.0 specification dictionary
    """
    # Create generator with override flag to use specified version instead of router's
    generator = OpenAPIGenerator(
        title=title,
        description=description,
        version=version,
        override_router_version=True,
        **kwargs,
    )
    return await generator.generate_from_application(app)


async def generate_openapi_from_apis(
    apis: Dict[str, API],
    title: str = "API Documentation",
    description: str = "Auto-generated API documentation",
    version: str = "1.0.0",
    **kwargs,
) -> Dict[str, Any]:
    """
    Convenience function to generate OpenAPI spec from a dictionary of APIs.

    Args:
        apis: Dictionary of API instances
        title: API title
        description: API description
        version: API version (overrides router's version)
        **kwargs: Additional arguments for OpenAPIGenerator

    Returns:
        OpenAPI 3.0 specification dictionary
    """
    # Create a simple router-like object
    class SimpleRouter:
        def __init__(self, apis):
            self.apis = apis
    
    router = SimpleRouter(apis)
    # Create generator with override flag to use specified version instead of router's
    generator = OpenAPIGenerator(
        title=title,
        description=description,
        version=version,
        override_router_version=True,
        **kwargs,
    )
    return await generator.generate_from_router(router)
