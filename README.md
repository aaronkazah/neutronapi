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
from neutronapi.base import API, endpoint

class PostAPI(API):
    resource = "/posts"
    name = "posts"
    
    @endpoint("/", methods=["GET"])
    async def list_posts(self, scope, receive, send, **kwargs):
        # Access registry dependencies
        logger = self.registry.get('utils:logger')
        cache = self.registry.get('services:cache')
        
        posts = [{"id": 1, "title": "Hello World"}]
        return await self.response(posts)
    
    @endpoint("/", methods=["POST"])
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
from neutronapi.base import API, Response, endpoint
from neutronapi.application import Application

class TypedAPI(API):
    resource = "/api"
    
    @endpoint("/users", methods=["GET"])
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
from neutronapi.base import API, endpoint
from neutronapi.application import Application

class CleanupTask(Task):
    name = "cleanup"
    frequency = TaskFrequency.MINUTELY
    
    async def run(self, **kwargs):
        print("Cleaning up logs...")

class PingAPI(API):
    resource = "/ping"
    
    @endpoint("/", methods=["GET"])
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

## Database Features

### Models & ORM
```python
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, IntegerField, DateTimeField

class Post(Model):
    title = CharField(max_length=200)
    content = TextField()
    created_at = DateTimeField(auto_now_add=True)

# Basic queries
await Post.objects.all()
await Post.objects.filter(title="My Post")
await Post.objects.create(title="New Post", content="...")
```

### Full-Text Search
```python
# Search across text fields
await Post.objects.search("python framework")

# Field-specific search
await Post.objects.filter(content__search="database")

# Ranked results (PostgreSQL/SQLite FTS5)
await Post.objects.search("api").order_by_rank()
```

Supports PostgreSQL native FTS and SQLite FTS5 with automatic fallback to LIKE queries.


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
@endpoint("/upload", methods=["POST"], middlewares=[AuthMiddleware()])
async def upload_file(self, scope, receive, send, **kwargs):
    # This endpoint has auth middleware
    pass
```

## Parsers

```python
from neutronapi.parsers import FormParser, MultiPartParser, BinaryParser

# Default: JSON parser
@endpoint("/api/data", methods=["POST"])
async def json_data(self, scope, receive, send, **kwargs):
    data = kwargs["body"]  # Parsed JSON dict
    return await self.response({"received": data})

# Custom parsers
@endpoint("/upload", methods=["POST"], parsers=[MultiPartParser(), FormParser()])
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
    @endpoint("/orders", methods=["POST"])
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

@endpoint("/users/<int:user_id>", methods=["GET"])
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

Exceptions are organized by module:

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

## OpenAPI Documentation

Generate OpenAPI 3.0 specifications from your code:

```python
from neutronapi.openapi.openapi import OpenAPIGenerator

# Add documentation to endpoints
class UserAPI(API):
    resource = "/users"
    name = "users"
    
    @endpoint("/", methods=["GET"], 
              summary="List users",
              response_schema={
                  "type": "object",
                  "properties": {
                      "users": {"type": "array"},
                      "total": {"type": "integer"}
                  }
              })
    async def list_users(self, scope, receive, send, **kwargs):
        return await self.response({"users": [], "total": 0})

# Generate specification
async def generate_docs():
    import json
    generator = OpenAPIGenerator(title="My API", version="1.0.0")
    spec = await generator.generate_from_application(app)
    
    with open('openapi.json', 'w') as f:
        json.dump(spec, f, indent=2)

# Use with external documentation tools (Swagger UI, Postman, etc.)
```

## Why NeutronAPI?

- **🚀 Performance**: Built on ASGI/uvicorn for maximum throughput
- **🏗️ Architecture**: Clean separation with universal dependency injection  
- **🔒 Type Safety**: Comprehensive typing with IDE support
- **📚 Auto Documentation**: OpenAPI 3.0 & Swagger 2.0 generation
- **🎯 Developer Experience**: Rich error messages, validation, and documentation
- **📦 Batteries Included**: ORM, migrations, background tasks, middleware
- **🔧 Production Ready**: Multi-worker support, monitoring, and deployment tools

Perfect for building modern APIs, microservices, and high-performance web applications with automatic documentation.
