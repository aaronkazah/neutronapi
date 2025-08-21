"""
CLI-only startproject command - not available in manage.py commands.
"""
import os
from typing import List


class Command:
    def __init__(self):
        self.help = "Create a new NeutronAPI project (CLI only)"

    async def handle(self, args: List[str]) -> None:
        if not args:
            print("Usage: neutronapi startproject <project_name> [destination_dir]")
            return

        project_name = args[0]
        dest = args[1] if len(args) > 1 else project_name

        if os.path.exists(dest) and os.listdir(dest):
            print(f"Destination '{dest}' already exists and is not empty.")
            return

        # Create basic structure
        os.makedirs(os.path.join(dest, 'apps'), exist_ok=True)

        # Create simple manage.py
        manage_content = '''#!/usr/bin/env python
"""
Simple manage.py for NeutronAPI project.
"""
import os
import sys

def main():
    # Set default settings module
    os.environ.setdefault('NEUTRONAPI_SETTINGS_MODULE', 'apps.settings')

    from neutronapi.cli import main as cli_main
    cli_main()

if __name__ == "__main__":
    main()
'''

        manage_path = os.path.join(dest, 'manage.py')
        with open(manage_path, 'w') as f:
            f.write(manage_content)

        try:
            os.chmod(manage_path, 0o755)
        except Exception:
            pass

        # Create apps/__init__.py
        with open(os.path.join(dest, 'apps', '__init__.py'), 'w') as f:
            f.write("# Apps package\n")

        # Create comprehensive settings.py
        settings_content = f'''"""
Settings for {project_name}.

For the full list of settings and their values, see:
https://docs.neutronapi.com/en/latest/ref/settings/
"""
import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# REQUIRED SETTINGS
# -----------------

# ASGI application entry point (REQUIRED)
# Points to your Application instance in module:variable format
ENTRY = "apps.entry:app"

# Database configuration (REQUIRED)
# At minimum, you must define a 'default' database
DATABASES = {{
    'default': {{
        'ENGINE': 'aiosqlite',  # or 'asyncpg' for PostgreSQL
        'NAME': ':memory:' if os.getenv('TESTING') == '1' else BASE_DIR / 'db.sqlite3',
        # For PostgreSQL, also add:
        # 'HOST': 'localhost',
        # 'PORT': 5432,
        # 'USER': 'your_user',
        # 'PASSWORD': 'your_password',
    }}
}}

# OPTIONAL SETTINGS
# -----------------

# Security settings
SECRET_KEY = os.getenv('SECRET_KEY', 'dev-key-change-in-production')
DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# Application settings
USE_TZ = True
TIME_ZONE = 'UTC'

# Logging configuration
LOGGING = {{
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {{
        'console': {{
            'class': 'logging.StreamHandler',
        }},
    }},
    'root': {{
        'handlers': ['console'],
        'level': 'INFO',
    }},
}}

# Background task settings
BACKGROUND_TASKS = {{
    'enabled': True,
    'max_workers': 4,
}}
'''

        with open(os.path.join(dest, 'apps', 'settings.py'), 'w') as f:
            f.write(settings_content)

        # Create minimal entry.py
        entry_content = f'''"""
Entry point for {project_name}.
"""
from neutronapi.application import Application
from neutronapi.base import API

class MainAPI(API):
    resource = ""  # Root path

    @API.endpoint("/", methods=["GET"])
    async def hello(self, scope, receive, send, **kwargs):
        return await self.response({{"message": "Hello from {project_name}!"}})

# Create the application with clean array syntax
app = Application(apis=[
    MainAPI(),
])
'''

        with open(os.path.join(dest, 'apps', 'entry.py'), 'w') as f:
            f.write(entry_content)

        print(f"✓ Project '{project_name}' created at '{dest}'.")
        print("Next steps:")
        print(f"  cd {dest}")
        print("  python manage.py test")
