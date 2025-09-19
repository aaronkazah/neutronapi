"""
Startapp command: scaffolds a new app under ./apps.

Usage:
  neutronapi startapp <app_name>
"""
import os
from typing import List


MODELS_TEMPLATE = """# Example models module for {app_name}
# Replace with your actual models once your ORM is in place.

class Example:
    pass
"""


class Command:
    def __init__(self):
        self.help = "Create a new app in ./apps"

    async def handle(self, args: List[str]) -> None:
        if not args or (args and args[0] == "--help"):
            print("Usage: neutronapi startapp <app_name>")
            print(f"Description: {self.help}")
            return

        app_name = args[0]
        base = os.path.join(os.getcwd(), 'apps', app_name)

        if os.path.exists(base):
            print(f"App '{app_name}' already exists at {base}")
            return

        # Create directories
        os.makedirs(os.path.join(base, 'migrations'), exist_ok=True)
        os.makedirs(os.path.join(base, 'tests'), exist_ok=True)
        os.makedirs(os.path.join(base, 'commands'), exist_ok=True)

        # __init__.py files
        for p in [base, os.path.join(base, 'migrations'), os.path.join(base, 'tests')]:
            with open(os.path.join(p, '__init__.py'), 'w') as f:
                f.write("")

        # models.py
        with open(os.path.join(base, 'models.py'), 'w') as f:
            f.write(MODELS_TEMPLATE.format(app_name=app_name))

        print(f"✓ App '{app_name}' created at apps/{app_name}")
