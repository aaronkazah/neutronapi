# NeutronAPI

**A fast Python web framework that's like Django, but built for modern async applications.**

Stop fighting with complex setups. NeutronAPI gives you everything you need to build APIs quickly: database models, migrations, background tasks, and a simple command-line interface. Perfect if you want the power of Django but with async performance.

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
        posts = [{"id": 1, "title": "Hello World"}]
        return await self.response(posts)
    
    @API.endpoint("/", methods=["POST"])
    async def create_post(self, scope, receive, send, **kwargs):
        # JSON parser is the default; access body via kwargs
        data = kwargs["body"]  # dict
        return await self.response({"id": 2, "title": data.get("title", "New Post")})
```

**5. Register API, Middlewares, Services in `apps/entry.py`**
```python
from neutronapi.application import Application
from neutronapi.middleware.compression import CompressionMiddleware
from neutronapi.middleware.allowed_hosts import AllowedHostsMiddleware
from apps.posts.api import PostAPI

# Middlewares and services are instances only
app = Application(
    apis=[PostAPI()],
    middlewares=[
        AllowedHostsMiddleware(allowed_hosts=["localhost", "127.0.0.1"]),
        CompressionMiddleware(minimum_size=512),
    ],
    services=[
        # Example: EventBus(id="event_bus"), EmailService(id="email")
    ],
)
```

**6. Start Server**
```bash
python manage.py start
# Visit: http://127.0.0.1:8000/posts
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

## Services (Optional - Dependency Injection)

Services provide dependency injection for shared components like databases, email, caching, etc. You don't have to use them - they're just a clean way to share dependencies across your APIs.

```python
# Email service example
class EmailService:
    def __init__(self):
        self.id = "email"  # Required
    
    async def send(self, to, subject, body):
        # Your email logic here
        pass

app = Application(
    apis=[UserAPI()],
    services=[EmailService()]  # Optional - only if you need dependency injection
)

# Access in your API
class UserAPI(API):
    @API.endpoint("/register", methods=["POST"])
    async def register(self, scope, receive, send, **kwargs):
        # Use the service
        await self.services["email"].send("user@example.com", "Welcome!", "Hello!")
        return await self.response({"status": "registered"})
```

## Exceptions

```python
from neutronapi.exceptions import ValidationError, NotFound

@API.endpoint("/users/<int:user_id>", methods=["GET"])
async def get_user(self, scope, receive, send, **kwargs):
    user_id = kwargs["user_id"]
    
    if not user_id:
        raise ValidationError("User ID is required")
    
    user = await get_user_from_db(user_id)
    if not user:
        raise NotFound("User not found")
    
    return await self.response(user)
```
