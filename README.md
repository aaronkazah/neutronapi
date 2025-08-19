# NeutronAPI

**High-performance Python framework built directly on uvicorn with built-in database models, migrations, and background tasks. If you want Django that was built async-first, this is for you.**

Batteries included async API framework with command-line management.

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
    name = "posts"
    
    @API.endpoint("/posts", methods=["GET"])
    async def list_posts(self, scope, receive, send, **kwargs):
        posts = [{"id": 1, "title": "Hello World"}]
        return await self.response(posts)
    
    @API.endpoint("/posts", methods=["POST"])
    async def create_post(self, scope, receive, send, **kwargs):
        # Get request data from scope["body"]
        return await self.response({"id": 2, "title": "New Post"})
```

**5. Register API in `apps/entry.py`**
```python
from neutronapi.application import Application
from apps.posts.api import PostAPI

app = Application({
    "posts": PostAPI()
})
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

class CleanupTask(Task):
    name = "cleanup"
    frequency = TaskFrequency.MINUTELY
    
    async def run(self, **kwargs):
        print("Cleaning up logs...")

# Add to application
app = Application(
    apis={"ping": PingAPI()},
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
```

## Commands

```bash
python manage.py start              # Start server
python manage.py test               # Run tests  
python manage.py migrate            # Run migrations
python manage.py startapp posts     # Create new app
```
