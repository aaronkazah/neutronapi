# NeutronAPI

**A modern, high-performance Python web framework built for async applications.**

NeutronAPI provides everything you need to build robust APIs quickly: universal dependency injection, comprehensive type support, database models with migrations, background tasks, and an intuitive command-line interface. Designed for performance, developer experience, and production readiness.

## Installation

```bash
pip install neutronapi
```

## Quick Start

```bash
# 1. Create project
neutronapi startproject blog
cd blog

# 2. Create an app
python manage.py startapp posts

# 3. Start server  
python manage.py start               # Dev mode (auto-reload)

# 4. Test
python manage.py test
```

## Key Features

✅ **Universal Registry System** - Clean dependency injection with `namespace:name` keys  
✅ **Comprehensive Type Support** - Full typing with IDE integration  
✅ **High Performance** - Built on uvicorn/ASGI for maximum speed  
✅ **Database ORM** - Models, migrations, and async queries  
✅ **Background Tasks** - Scheduled and async task execution  
✅ **Developer Experience** - Rich docstrings, validation, and error messages  

## Getting Started Tutorial

**1. Create Project**
```bash
neutronapi startproject blog
cd blog
```

**2. Create App Module**  
```bash
python manage.py startapp posts
```

**3. Configure in `apps/settings.py`**
```python
import os

# ASGI application entry point (required for server)
ENTRY = "apps.entry:app"  # module:variable format

# Database
DATABASES = {
    'default': {
        'ENGINE': 'aiosqlite',
        'NAME': 'db.sqlite3',
    }
}
```

**4. Create API in `apps/posts/api.py`**
```python
from neutronapi.base import API

class PostAPI(API):
    resource = "/posts"
    name = "posts"
    
    @API.endpoint("/", methods=["GET"])
    async def list_posts(self, scope, receive, send, **kwargs):
        # Access registry dependencies
        logger = self.registry.get('utils:logger')
        cache = self.registry.get('services:cache')
        
        posts = [{"id": 1, "title": "Hello World"}]
        return await self.response(posts)
    
    @API.endpoint("/", methods=["POST"])
    async def create_post(self, scope, receive, send, **kwargs):
        # JSON parser is the default; access body via kwargs
        data = kwargs["body"]  # dict
        return await self.response({"id": 2, "title": data.get("title", "New Post")})
```

**5. Register API, Middlewares, Dependencies in `apps/entry.py`**
```python
from neutronapi.application import Application
from neutronapi.middleware.compression import CompressionMiddleware
from neutronapi.middleware.allowed_hosts import AllowedHostsMiddleware
from apps.posts.api import PostAPI

# Example dependencies
class Logger:
    def info(self, message: str) -> None:
        print(f"[INFO] {message}")

class CacheService:
    def __init__(self):
        self._cache = {}
    
    def get(self, key: str) -> any:
        return self._cache.get(key)
    
    def set(self, key: str, value: any) -> None:
        self._cache[key] = value

# Modern registry-based dependency injection
app = Application(
    apis=[PostAPI()],
    middlewares=[
        AllowedHostsMiddleware(allowed_hosts=["localhost", "127.0.0.1"]),
        CompressionMiddleware(minimum_size=512),
    ],
    registry={
        'utils:logger': Logger(),
        'services:cache': CacheService(),
        'services:email': EmailService(),
    }
)
```

**6. Start Server**
```bash
python manage.py start
# Visit: http://127.0.0.1:8000/posts
```

## Universal Registry System

The registry provides clean dependency injection with namespaced keys:

```python
from neutronapi.application import Application

# Register dependencies with namespace:name pattern
app = Application(
    registry={
        'utils:logger': Logger(),
        'utils:cache': RedisCache(),
        'services:email': EmailService(), 
        'services:database': DatabaseService(),
        'modules:auth': AuthModule(),
    }
)

# Access in APIs
class UserAPI(API):
    @API.endpoint("/register", methods=["POST"])
    async def register(self, scope, receive, send, **kwargs):
        # Type-safe access with IDE support
        logger = self.registry.get('utils:logger')
        email = self.registry.get('services:email')
        
        logger.info("User registration started")
        await email.send_welcome_email(user_data)
        
        return await self.response({"status": "registered"})

# Dynamic registration
app.register('utils:metrics', MetricsCollector())
app.register('services:payment', PaymentProcessor())

# Registry utilities
print(app.list_registry_keys())  # All keys
print(app.list_registry_keys('utils'))  # Just utils namespace
print(app.has_registry_item('services:email'))  # True
```

## Comprehensive Type Support

NeutronAPI includes full type hints with IDE integration:

```python
from typing import Dict, List, Optional
from neutronapi.base import API, Response
from neutronapi.application import Application

class TypedAPI(API):
    resource = "/api"
    
    @API.endpoint("/users", methods=["GET"])
    async def get_users(self, scope: Dict[str, Any], receive, send) -> Response:
        # Full type support with autocomplete
        cache: CacheService = self.registry.get('services:cache')
        users: List[Dict[str, str]] = cache.get('users') or []
        
        return await self.response(users)

# Type-safe registry access
def get_typed_dependency[T](app: Application, key: str) -> Optional[T]:
    return app.get_registry_item(key)

logger = get_typed_dependency[Logger](app, 'utils:logger')
```

## Project Structure

```
myproject/
├── manage.py           # Management commands
├── apps/
│   ├── __init__.py
│   ├── settings.py     # Configuration 
│   └── entry.py        # ASGI application
└── db.sqlite3          # Database
```

## Background Tasks

```python
from neutronapi.background import Task, TaskFrequency
from neutronapi.base import API
from neutronapi.application import Application

class CleanupTask(Task):
    name = "cleanup"
    frequency = TaskFrequency.MINUTELY
    
    async def run(self, **kwargs):
        print("Cleaning up logs...")

class PingAPI(API):
    resource = "/ping"
    
    @API.endpoint("/", methods=["GET"])
    async def ping(self, scope, receive, send, **kwargs):
        return await self.response({"status": "ok"})

# Add to application  
app = Application(
    apis=[PingAPI()],
    tasks={"cleanup": CleanupTask()}
)
```

## Database Models

```python
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, IntegerField, DateTimeField

class User(Model):
    name = CharField(max_length=100)
    age = IntegerField()
    created_at = DateTimeField(auto_now_add=True)
```

## Server Commands

```bash
# Development (auto-reload, localhost)
python manage.py start

# Production (multi-worker, optimized)  
python manage.py start --production

# Custom configuration
python manage.py start --host 0.0.0.0 --port 8080 --workers 4
```

## Testing

```bash
# SQLite (default)
python manage.py test

# Specific tests
python manage.py test app.tests.test_models.TestUser.test_creation

# Dev tooling (only neutronapi/ is targeted)
black neutronapi
flake8 neutronapi
```

## Commands

```bash
python manage.py start              # Start server
python manage.py test               # Run tests  
python manage.py migrate            # Run migrations
python manage.py startapp posts     # Create new app
```

## Middlewares

```python
from neutronapi.middleware.compression import CompressionMiddleware
from neutronapi.middleware.allowed_hosts import AllowedHostsMiddleware

app = Application(
    apis=[PostAPI()],
    middlewares=[
        AllowedHostsMiddleware(allowed_hosts=["localhost", "yourdomain.com"]),
        CompressionMiddleware(minimum_size=512),  # Compress responses > 512 bytes
    ]
)

# Endpoint-level middleware
@API.endpoint("/upload", methods=["POST"], middlewares=[AuthMiddleware()])
async def upload_file(self, scope, receive, send, **kwargs):
    # This endpoint has auth middleware
    pass
```

## Parsers

```python
from neutronapi.parsers import FormParser, MultiPartParser, BinaryParser

# Default: JSON parser
@API.endpoint("/api/data", methods=["POST"])
async def json_data(self, scope, receive, send, **kwargs):
    data = kwargs["body"]  # Parsed JSON dict
    return await self.response({"received": data})

# Custom parsers
@API.endpoint("/upload", methods=["POST"], parsers=[MultiPartParser(), FormParser()])
async def upload_file(self, scope, receive, send, **kwargs):
    files = kwargs["files"]  # Uploaded files
    form_data = kwargs["form"]  # Form fields
    return await self.response({"status": "uploaded"})
```

## Advanced Registry Usage

```python
from neutronapi.application import Application
from typing import Protocol

# Define interfaces for better type safety
class EmailServiceProtocol(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...

class MetricsProtocol(Protocol):
    def increment(self, metric: str) -> None: ...

# Implementation
class SMTPEmailService:
    async def send(self, to: str, subject: str, body: str) -> None:
        # SMTP implementation
        pass

class PrometheusMetrics:
    def increment(self, metric: str) -> None:
        # Prometheus implementation
        pass

# Register with clear namespacing
app = Application(
    registry={
        'services:email': SMTPEmailService(),
        'services:metrics': PrometheusMetrics(),
        'utils:logger': StructuredLogger(),
        'modules:auth': JWTAuthModule(),
    }
)

# Usage with type safety
class OrderAPI(API):
    @API.endpoint("/orders", methods=["POST"])
    async def create_order(self, scope, receive, send, **kwargs):
        email: EmailServiceProtocol = self.registry.get('services:email')
        metrics: MetricsProtocol = self.registry.get('services:metrics')
        
        # Your business logic here
        metrics.increment('orders.created')
        await email.send('user@example.com', 'Order Confirmed', 'Thanks!')
        
        return await self.response({"status": "created"})
```

## Error Handling

```python
from neutronapi.api.exceptions import ValidationError, NotFound, APIException

@API.endpoint("/users/<int:user_id>", methods=["GET"])
async def get_user(self, scope, receive, send, **kwargs):
    user_id = kwargs["user_id"]
    
    if not user_id:
        raise ValidationError("User ID is required")
    
    user = await get_user_from_db(user_id)
    if not user:
        raise NotFound("User not found")
    
    return await self.response(user)

# Custom exceptions
class BusinessLogicError(APIException):
    status_code = 422
    
    def __init__(self, message: str = "Business logic error"):
        super().__init__(message, type="business_error")
```

### Exception Organization

Exceptions are organized by module (like Django):

```python
# Module-specific exceptions
from neutronapi.api.exceptions import APIException, ValidationError, NotFound
from neutronapi.db.exceptions import DoesNotExist, MigrationError, IntegrityError
from neutronapi.authentication.exceptions import AuthenticationFailed
from neutronapi.middleware.exceptions import RouteNotFound, MethodNotAllowed
from neutronapi.openapi.exceptions import InvalidSchemaError

# Generic framework exceptions
from neutronapi.exceptions import ImproperlyConfigured, ValidationError, ObjectDoesNotExist
```

## OpenAPI & Swagger Documentation

NeutronAPI includes comprehensive OpenAPI 3.0 and Swagger support with automatic spec generation. **Documentation hosting is completely optional and under your control:**

```python
from neutronapi.base import API
from neutronapi.application import Application
from neutronapi.openapi.openapi import OpenAPIGenerator
from neutronapi.openapi.swagger import SwaggerConverter

class UserAPI(API):
    resource = "/users"
    title = "User Management"
    description = "User registration and management endpoints"
    tags = ["Users"]
    
    @API.endpoint("/", methods=["GET"], 
                  summary="List all users",
                  description="Retrieve a paginated list of all users",
                  tags=["Users"],
                  response_schema={
                      "type": "object",
                      "properties": {
                          "users": {
                              "type": "array",
                              "items": {
                                  "type": "object",
                                  "properties": {
                                      "id": {"type": "integer"},
                                      "name": {"type": "string"},
                                      "email": {"type": "string", "format": "email"}
                                  }
                              }
                          },
                          "total": {"type": "integer"},
                          "page": {"type": "integer"}
                      }
                  },
                  parameters=[
                      {
                          "name": "page",
                          "in": "query",
                          "description": "Page number",
                          "required": False,
                          "schema": {"type": "integer", "default": 1}
                      }
                  ])
    async def list_users(self, scope, receive, send, **kwargs):
        page = int(kwargs.get('params', {}).get('page', 1))
        users = [{"id": 1, "name": "John", "email": "john@example.com"}]
        return await self.response({"users": users, "total": 1, "page": page})
    
    @API.endpoint("/", methods=["POST"],
                  summary="Create new user",
                  description="Register a new user account",
                  request_schema={
                      "type": "object",
                      "required": ["name", "email"],
                      "properties": {
                          "name": {"type": "string", "minLength": 2},
                          "email": {"type": "string", "format": "email"},
                          "age": {"type": "integer", "minimum": 13}
                      }
                  },
                  response_schema={
                      "type": "object",
                      "properties": {
                          "id": {"type": "integer"},
                          "name": {"type": "string"},
                          "email": {"type": "string"},
                          "created_at": {"type": "string", "format": "date-time"}
                      }
                  },
                  responses={
                      400: {
                          "description": "Validation error",
                          "schema": {
                              "type": "object",
                              "properties": {
                                  "error": {"type": "string"}
                              }
                          }
                      }
                  })
    async def create_user(self, scope, receive, send, **kwargs):
        data = kwargs["body"]
        user = {"id": 123, "name": data["name"], "email": data["email"], "created_at": "2023-01-01T00:00:00Z"}
        return await self.response(user, status_code=201)

app = Application(apis=[UserAPI()])
```

### Generate OpenAPI Specification

```python
import asyncio
from neutronapi.openapi.openapi import OpenAPIGenerator

# Generate from entire application
async def generate_docs():
    generator = OpenAPIGenerator(
        title="My API",
        description="A comprehensive REST API built with NeutronAPI",
        version="1.0.0",
        servers=[
            {"url": "https://api.example.com", "description": "Production server"},
            {"url": "https://staging-api.example.com", "description": "Staging server"}
        ],
        contact={
            "name": "API Support",
            "url": "https://example.com/support",
            "email": "support@example.com"
        },
        license_info={
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT"
        }
    )
    
    # Generate from Application instance
    openapi_spec = await generator.generate_from_application(app)
    
    # Generate from individual API
    user_api_spec = await generator.generate_from_api(UserAPI())
    
    # Save to file
    import json
    with open('openapi.json', 'w') as f:
        json.dump(openapi_spec, f, indent=2)
    
    return openapi_spec

# Run the generator
spec = asyncio.run(generate_docs())
print("OpenAPI spec generated!")
```

### Convert to Swagger 2.0

```python
from neutronapi.openapi.swagger import SwaggerConverter

# Convert OpenAPI 3.0 to Swagger 2.0 for legacy compatibility
converter = SwaggerConverter()
swagger_spec = converter.convert_openapi_to_swagger(openapi_spec)

# Save Swagger spec
with open('swagger.json', 'w') as f:
    json.dump(swagger_spec, f, indent=2)
```

### Optional: Serve Interactive Documentation

**Note**: NeutronAPI **never automatically hosts documentation**. You have complete control over where and how to serve your API docs.

```python
from neutronapi.base import API
from neutronapi.application import Application

# OPTIONAL: Create a docs API only if you want to self-host documentation
class DocsAPI(API):
    resource = "/docs"  # You choose the path - could be /api-docs, /documentation, etc.
    
    @API.endpoint("/openapi.json", methods=["GET"])
    async def openapi_spec(self, scope, receive, send, **kwargs):
        """Serve OpenAPI specification - completely optional endpoint"""
        generator = OpenAPIGenerator(
            title="My API Documentation",
            description="Auto-generated API documentation",
            version="1.0.0"
        )
        spec = await generator.generate_from_application(self.app)
        return await self.response(spec)
    
    @API.endpoint("/", methods=["GET"])
    async def swagger_ui(self, scope, receive, send, **kwargs):
        """Serve Swagger UI"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>API Documentation</title>
            <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@3.52.5/swagger-ui.css" />
        </head>
        <body>
            <div id="swagger-ui"></div>
            <script src="https://unpkg.com/swagger-ui-dist@3.52.5/swagger-ui-bundle.js"></script>
            <script>
                SwaggerUIBundle({
                    url: '/docs/openapi.json',
                    dom_id: '#swagger-ui',
                    presets: [
                        SwaggerUIBundle.presets.apis,
                        SwaggerUIBundle.presets.standalone
                    ]
                });
            </script>
        </body>
        </html>
        """
        return await self.response(html, headers=[(b"content-type", b"text/html")])

# COMPLETELY OPTIONAL: Only add DocsAPI if you want self-hosted docs
app = Application(
    apis=[
        UserAPI(),
        DocsAPI()  # Only include this if you want docs at /docs
    ]
)

# Alternative: Generate specs for external hosting (recommended for production)
async def export_specs():
    generator = OpenAPIGenerator(title="My API", version="1.0.0")
    spec = await generator.generate_from_application(app)
    
    # Export to file for external hosting (Postman, Insomnia, etc.)
    with open('api-spec.json', 'w') as f:
        json.dump(spec, f, indent=2)
    
    # Or upload to external documentation service
    # await upload_to_readme_io(spec)
    # await upload_to_postman(spec)
```

### Advanced Schema Patterns

```python
# Reusable schema components
USER_SCHEMA = {
    "type": "object",
    "required": ["name", "email"],
    "properties": {
        "id": {"type": "integer", "description": "Unique user identifier"},
        "name": {"type": "string", "minLength": 2, "maxLength": 100},
        "email": {"type": "string", "format": "email"},
        "age": {"type": "integer", "minimum": 13, "maximum": 120},
        "created_at": {"type": "string", "format": "date-time"},
        "profile": {
            "type": "object",
            "properties": {
                "bio": {"type": "string", "maxLength": 500},
                "avatar_url": {"type": "string", "format": "uri"}
            }
        }
    }
}

ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "message": {"type": "string"}
            }
        }
    }
}

class AdvancedUserAPI(API):
    resource = "/users"
    
    @API.endpoint("/<int:user_id>", methods=["GET"],
                  summary="Get user by ID",
                  parameters=[
                      {
                          "name": "user_id",
                          "in": "path",
                          "required": True,
                          "schema": {"type": "integer"},
                          "description": "User ID"
                      },
                      {
                          "name": "include",
                          "in": "query",
                          "schema": {
                              "type": "array",
                              "items": {"type": "string", "enum": ["profile", "posts"]}
                          },
                          "description": "Additional data to include"
                      }
                  ],
                  response_schema=USER_SCHEMA,
                  responses={
                      404: {"description": "User not found", "schema": ERROR_SCHEMA}
                  })
    async def get_user(self, scope, receive, send, **kwargs):
        user_id = kwargs["user_id"]
        # Your logic here
        return await self.response({"id": user_id, "name": "John", "email": "john@example.com"})
```

## Documentation Deployment Options

NeutronAPI gives you **complete control** over how to deploy your API documentation:

### 1. **External Documentation Services** (Recommended)
```python
# Generate spec for external hosting
spec = await generator.generate_from_application(app)

# Popular external documentation platforms:
# - readme.io
# - GitBook
# - Postman Documentation
# - Insomnia Documentation
# - Stoplight
# - SwaggerHub
```

### 2. **Static File Hosting**
```python
# Generate static files for CDN/static hosting
import json

spec = await generator.generate_from_application(app)

# Save for static hosting (GitHub Pages, Netlify, etc.)
with open('public/openapi.json', 'w') as f:
    json.dump(spec, f)

# Generate static Swagger UI
swagger_html = f"""
<!DOCTYPE html>
<html>
<head><title>API Docs</title></head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist/swagger-ui-bundle.js"></script>
    <script>
        SwaggerUIBundle({{
            url: './openapi.json',
            dom_id: '#swagger-ui'
        }});
    </script>
</body>
</html>
"""
with open('public/index.html', 'w') as f:
    f.write(swagger_html)
```

### 3. **Self-Hosted (Optional)**
```python
# Only if you want to serve docs from your API server
class OptionalDocsAPI(API):
    resource = "/internal-docs"  # You control the path
    
    @API.endpoint("/spec", methods=["GET"])
    async def spec(self, scope, receive, send, **kwargs):
        # Your choice to include this endpoint
        spec = await generator.generate_from_application(self.app)
        return await self.response(spec)

# Add only if you explicitly want self-hosted docs
app = Application(
    apis=[
        UserAPI(),
        # OptionalDocsAPI()  # Uncomment only if desired
    ]
)
```

### 4. **CI/CD Integration**
```python
# Example: GitHub Actions workflow
# .github/workflows/docs.yml
"""
name: Generate API Docs
on: [push]
jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Generate OpenAPI spec
        run: |
          python -c "
          import asyncio
          from your_app import app
          from neutronapi.openapi.openapi import OpenAPIGenerator
          
          async def generate():
              gen = OpenAPIGenerator(title='My API', version='1.0.0')
              spec = await gen.generate_from_application(app)
              with open('openapi.json', 'w') as f:
                  json.dump(spec, f, indent=2)
          
          asyncio.run(generate())
          "
      - name: Deploy to documentation service
        run: |
          # Upload to your chosen documentation platform
          curl -X POST https://api.readme.io/api/v1/api-specification \
            -H "authorization: Basic $README_API_KEY" \
            -F "spec=@openapi.json"
"""
```

## Key Principles

- **🔒 No Magic**: Documentation hosting is explicit and optional
- **🎯 Developer Control**: You choose where and how to serve docs  
- **📋 Spec Generation**: Automatic OpenAPI generation from your code
- **🔄 Multiple Formats**: OpenAPI 3.0, Swagger 2.0, and custom exports
- **🚀 External Integration**: Works with all major documentation platforms

## Why NeutronAPI?

- **🚀 Performance**: Built on ASGI/uvicorn for maximum throughput
- **🏗️ Architecture**: Clean separation with universal dependency injection  
- **🔒 Type Safety**: Comprehensive typing with IDE support
- **📚 Auto Documentation**: OpenAPI 3.0 & Swagger 2.0 generation
- **🎯 Developer Experience**: Rich error messages, validation, and documentation
- **📦 Batteries Included**: ORM, migrations, background tasks, middleware
- **🔧 Production Ready**: Multi-worker support, monitoring, and deployment tools

Perfect for building modern APIs, microservices, and high-performance web applications with automatic documentation.