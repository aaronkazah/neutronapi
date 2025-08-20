#!/usr/bin/env python3
"""
Swagger converter for OpenAPI specifications.

This module provides functionality to convert OpenAPI 3.0+ specifications
to Swagger 2.0 format for backward compatibility with older tools and clients.
"""

from typing import Dict, Any, Optional, List
import copy


class SwaggerConverter:
    """Converts OpenAPI 3.0+ specifications to Swagger 2.0 format."""

    def __init__(self):
        self.converted_schemas = {}
        self.converted_parameters = {}

    def convert_openapi_to_swagger(
        self, openapi_spec: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Convert an OpenAPI 3.0+ specification to Swagger 2.0 format.

        Args:
            openapi_spec: OpenAPI 3.0+ specification dictionary

        Returns:
            Swagger 2.0 specification dictionary
        """
        # Reset conversion state
        self.converted_schemas = {}
        self.converted_parameters = {}

        swagger_spec = {
            "swagger": "2.0",
            "info": self._convert_info(openapi_spec.get("info", {})),
            "basePath": self._extract_base_path(openapi_spec),
            "schemes": self._extract_schemes(openapi_spec),
            "consumes": ["application/json"],
            "produces": ["application/json"],
            "paths": self._convert_paths(openapi_spec.get("paths", {})),
        }

        # Add host if present
        host = self._extract_host(openapi_spec)
        if host:
            swagger_spec["host"] = host

        # Add definitions if we have converted schemas
        if self.converted_schemas:
            swagger_spec["definitions"] = self.converted_schemas

        # Add parameters if we have converted parameters
        if self.converted_parameters:
            swagger_spec["parameters"] = self.converted_parameters

        # Add security definitions if present
        if (
            "components" in openapi_spec
            and "securitySchemes" in openapi_spec["components"]
        ):
            swagger_spec["securityDefinitions"] = self._convert_security_schemes(
                openapi_spec["components"]["securitySchemes"]
            )

        # Add tags if present
        if "tags" in openapi_spec:
            swagger_spec["tags"] = openapi_spec["tags"]

        return swagger_spec

    def _convert_info(self, info: Dict[str, Any]) -> Dict[str, Any]:
        """Convert OpenAPI info object to Swagger info object."""
        swagger_info = {
            "title": info.get("title", "API"),
            "version": info.get("version", "1.0.0"),
        }

        if "description" in info:
            swagger_info["description"] = info["description"]

        if "termsOfService" in info:
            swagger_info["termsOfService"] = info["termsOfService"]

        if "contact" in info:
            swagger_info["contact"] = info["contact"]

        if "license" in info:
            swagger_info["license"] = info["license"]

        return swagger_info

    def _extract_base_path(self, openapi_spec: Dict[str, Any]) -> str:
        """Extract base path from OpenAPI servers."""
        servers = openapi_spec.get("servers", [])
        if servers and "url" in servers[0]:
            url = servers[0]["url"]
            # Extract path from URL
            if "://" in url:
                # Full URL, extract path
                parts = url.split("://", 1)[1].split("/", 1)
                return f"/{parts[1]}" if len(parts) > 1 else "/"
            else:
                # Relative path
                return url if url.startswith("/") else f"/{url}"
        return "/"

    def _extract_schemes(self, openapi_spec: Dict[str, Any]) -> List[str]:
        """Extract schemes from OpenAPI servers."""
        servers = openapi_spec.get("servers", [])
        schemes = set()

        for server in servers:
            url = server.get("url", "")
            if "://" in url:
                scheme = url.split("://")[0]
                schemes.add(scheme)

        return list(schemes) if schemes else ["https"]

    def _extract_host(self, openapi_spec: Dict[str, Any]) -> Optional[str]:
        """Extract host from OpenAPI servers."""
        servers = openapi_spec.get("servers", [])
        if servers and "url" in servers[0]:
            url = servers[0]["url"]
            # Extract host from URL
            if "://" in url:
                # Full URL, extract host
                parts = url.split("://", 1)[1].split("/", 1)
                return parts[0]  # This is the host:port part
        return None

    def _convert_paths(self, paths: Dict[str, Any]) -> Dict[str, Any]:
        """Convert OpenAPI paths to Swagger paths."""
        swagger_paths = {}

        for path, path_item in paths.items():
            swagger_path_item = {}

            for method, operation in path_item.items():
                if method.lower() in [
                    "get",
                    "post",
                    "put",
                    "delete",
                    "patch",
                    "head",
                    "options",
                ]:
                    swagger_path_item[method.lower()] = self._convert_operation(
                        operation
                    )

            if swagger_path_item:
                swagger_paths[path] = swagger_path_item

        return swagger_paths

    def _convert_operation(self, operation: Dict[str, Any]) -> Dict[str, Any]:
        """Convert OpenAPI operation to Swagger operation."""
        swagger_operation = {}

        # Basic operation properties
        for prop in ["tags", "summary", "description", "operationId", "deprecated"]:
            if prop in operation:
                swagger_operation[prop] = operation[prop]

        # Convert parameters
        if "parameters" in operation:
            swagger_operation["parameters"] = [
                self._convert_parameter(param) for param in operation["parameters"]
            ]
        else:
            swagger_operation["parameters"] = []

        # Convert request body to parameter
        if "requestBody" in operation:
            body_param = self._convert_request_body(operation["requestBody"])
            if body_param:
                swagger_operation["parameters"].append(body_param)

        # Convert responses
        swagger_operation["responses"] = self._convert_responses(
            operation.get("responses", {})
        )

        # Convert security
        if "security" in operation:
            swagger_operation["security"] = operation["security"]

        return swagger_operation

    def _convert_parameter(self, parameter: Dict[str, Any]) -> Dict[str, Any]:
        """Convert OpenAPI parameter to Swagger parameter."""
        swagger_param = {
            "name": parameter["name"],
            "in": parameter["in"],
        }

        if "description" in parameter:
            swagger_param["description"] = parameter["description"]

        if "required" in parameter:
            swagger_param["required"] = parameter["required"]
        elif parameter["in"] == "path":
            swagger_param["required"] = True

        # Convert schema to Swagger parameter properties
        if "schema" in parameter:
            schema = parameter["schema"]
            swagger_param.update(self._convert_schema_to_param_props(schema))

        return swagger_param

    def _convert_request_body(
        self, request_body: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Convert OpenAPI request body to Swagger body parameter."""
        content = request_body.get("content", {})

        # Look for JSON content
        json_content = None
        for content_type in ["application/json", "application/*", "*/*"]:
            if content_type in content:
                json_content = content[content_type]
                break

        if not json_content or "schema" not in json_content:
            return None

        swagger_param = {
            "name": "body",
            "in": "body",
            "schema": self._convert_schema(json_content["schema"]),
        }

        if "description" in request_body:
            swagger_param["description"] = request_body["description"]

        if request_body.get("required", False):
            swagger_param["required"] = True

        return swagger_param

    def _convert_responses(self, responses: Dict[str, Any]) -> Dict[str, Any]:
        """Convert OpenAPI responses to Swagger responses."""
        swagger_responses = {}

        for status_code, response in responses.items():
            swagger_response = {}

            if "description" in response:
                swagger_response["description"] = response["description"]
            else:
                swagger_response["description"] = f"Response {status_code}"

            # Convert content to schema
            if "content" in response:
                content = response["content"]
                # Look for JSON content
                json_content = None
                for content_type in ["application/json", "application/*", "*/*"]:
                    if content_type in content:
                        json_content = content[content_type]
                        break

                if json_content and "schema" in json_content:
                    swagger_response["schema"] = self._convert_schema(
                        json_content["schema"]
                    )

            swagger_responses[status_code] = swagger_response

        return swagger_responses

    def _convert_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Convert OpenAPI schema to Swagger schema."""
        if "$ref" in schema:
            # Handle references
            ref = schema["$ref"]
            if ref.startswith("#/components/schemas/"):
                schema_name = ref.split("/")[-1]
                return {"$ref": f"#/definitions/{schema_name}"}
            return schema

        swagger_schema = copy.deepcopy(schema)

        # Convert nested schemas
        if "properties" in swagger_schema:
            for prop_name, prop_schema in swagger_schema["properties"].items():
                swagger_schema["properties"][prop_name] = self._convert_schema(
                    prop_schema
                )

        if "items" in swagger_schema:
            swagger_schema["items"] = self._convert_schema(swagger_schema["items"])

        if "allOf" in swagger_schema:
            swagger_schema["allOf"] = [
                self._convert_schema(s) for s in swagger_schema["allOf"]
            ]

        if "oneOf" in swagger_schema:
            # Swagger 2.0 doesn't support oneOf, convert to anyOf comment
            del swagger_schema["oneOf"]
            if "description" not in swagger_schema:
                swagger_schema["description"] = "One of multiple possible schemas"

        if "anyOf" in swagger_schema:
            # Swagger 2.0 doesn't support anyOf, convert to description
            del swagger_schema["anyOf"]
            if "description" not in swagger_schema:
                swagger_schema["description"] = "Any of multiple possible schemas"

        return swagger_schema

    def _convert_schema_to_param_props(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Convert schema properties to Swagger parameter properties."""
        props = {}

        if "type" in schema:
            props["type"] = schema["type"]

        if "format" in schema:
            props["format"] = schema["format"]

        if "enum" in schema:
            props["enum"] = schema["enum"]

        if "default" in schema:
            props["default"] = schema["default"]

        if "minimum" in schema:
            props["minimum"] = schema["minimum"]

        if "maximum" in schema:
            props["maximum"] = schema["maximum"]

        if "minLength" in schema:
            props["minLength"] = schema["minLength"]

        if "maxLength" in schema:
            props["maxLength"] = schema["maxLength"]

        if "pattern" in schema:
            props["pattern"] = schema["pattern"]

        if "items" in schema:
            props["items"] = self._convert_schema_to_param_props(schema["items"])

        return props

    def _convert_security_schemes(
        self, security_schemes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert OpenAPI security schemes to Swagger security definitions."""
        swagger_security = {}

        for name, scheme in security_schemes.items():
            swagger_scheme = {}

            scheme_type = scheme.get("type", "")

            if scheme_type == "http":
                if scheme.get("scheme") == "bearer":
                    swagger_scheme["type"] = "apiKey"
                    swagger_scheme["name"] = "Authorization"
                    swagger_scheme["in"] = "header"
                elif scheme.get("scheme") == "basic":
                    swagger_scheme["type"] = "basic"
            elif scheme_type == "apiKey":
                swagger_scheme["type"] = "apiKey"
                swagger_scheme["name"] = scheme["name"]
                swagger_scheme["in"] = scheme["in"]
            elif scheme_type == "oauth2":
                swagger_scheme["type"] = "oauth2"
                if "flows" in scheme:
                    flows = scheme["flows"]
                    if "implicit" in flows:
                        swagger_scheme["flow"] = "implicit"
                        swagger_scheme["authorizationUrl"] = flows["implicit"][
                            "authorizationUrl"
                        ]
                    elif "authorizationCode" in flows:
                        swagger_scheme["flow"] = "accessCode"
                        swagger_scheme["authorizationUrl"] = flows["authorizationCode"][
                            "authorizationUrl"
                        ]
                        swagger_scheme["tokenUrl"] = flows["authorizationCode"][
                            "tokenUrl"
                        ]
                    elif "clientCredentials" in flows:
                        swagger_scheme["flow"] = "application"
                        swagger_scheme["tokenUrl"] = flows["clientCredentials"][
                            "tokenUrl"
                        ]
                    elif "password" in flows:
                        swagger_scheme["flow"] = "password"
                        swagger_scheme["tokenUrl"] = flows["password"]["tokenUrl"]

                    # Add scopes from any flow
                    for flow in flows.values():
                        if "scopes" in flow:
                            swagger_scheme["scopes"] = flow["scopes"]
                            break

            if swagger_scheme:
                swagger_security[name] = swagger_scheme

        return swagger_security


def convert_openapi_to_swagger(openapi_spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to convert OpenAPI specification to Swagger 2.0.

    Args:
        openapi_spec: OpenAPI 3.0+ specification dictionary

    Returns:
        Swagger 2.0 specification dictionary
    """
    converter = SwaggerConverter()
    return converter.convert_openapi_to_swagger(openapi_spec)


async def generate_swagger_from_application(
    app,
    title: str = "API Documentation",
    description: str = "API documentation generated from OpenAPI",
    version: str = "1.0.0",
    **kwargs,
) -> Dict[str, Any]:
    """
    Generate Swagger 2.0 specification from an application.

    Args:
        app: ASGI application instance
        title: API title
        description: API description
        version: API version
        **kwargs: Additional OpenAPI generation parameters

    Returns:
        Swagger 2.0 specification dictionary
    """
    from .openapi import generate_openapi_from_application

    # First generate OpenAPI spec
    openapi_spec = await generate_openapi_from_application(
        app, title=title, description=description, version=version, **kwargs
    )

    # Convert to Swagger
    return convert_openapi_to_swagger(openapi_spec)
