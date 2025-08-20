"""
CLI-only startproject command - not available in manage.py commands.
"""
import os
from typing import List


class Command:
    def __init__(self):
        self.help = "Create a new NeutronAPI project (CLI only)"

    def handle(self, args: List[str]) -> None:
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
import sys

def main():
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

        # Create minimal settings.py
        settings_content = f'''"""
Settings for {project_name}.
"""
import os

# Application entry point
ENTRY = "apps.entry:app"

# Database configuration
DATABASES = {{
    'default': {{
        'ENGINE': 'aiosqlite',
        'NAME': ':memory:' if os.getenv('TESTING') == '1' else 'db.sqlite3',
    }}
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
    @API.endpoint("/", methods=["GET"])
    async def hello(self, scope, receive, send):
        return await self.response({{"message": "Hello from {project_name}!"}})

# Create the application with the API
app = Application(apis={{"": MainAPI()}})
'''
        
        with open(os.path.join(dest, 'apps', 'entry.py'), 'w') as f:
            f.write(entry_content)

        print(f"✓ Project '{project_name}' created at '{dest}'.")
        print("Next steps:")
        print(f"  cd {dest}")
        print("  python manage.py test")