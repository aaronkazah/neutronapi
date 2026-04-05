"""
Interactive shell command.
Launch an interactive Python shell with project context.
"""
import os
import sys
import asyncio
from typing import List

from neutronapi.commands.base import BaseCommand
from neutronapi.exceptions import CommandError


class Command(BaseCommand):
    """Interactive shell command class."""

    def __init__(self):
        super().__init__()
        self.help = "Launch an interactive Python shell with the project initialized"

    async def handle(self, args: List[str]) -> int:
        """
        Launch an interactive Python shell with the project initialized.

        Usage:
            python manage.py shell              # Start interactive shell
            python manage.py shell --help       # Show help

        In the shell, you can use:
            from neutronapi.db import setup_databases, get_databases
            from neutronapi.db.models import Model
            from neutronapi.db.migrations import MigrationManager

            # Setup database
            setup_databases()
            manager = MigrationManager()
            await manager.bootstrap_all()
        """

        # Show help if requested
        if args and args[0] in ["--help", "-h", "help"]:
            self.stdout(f"{self.help}\n")
            self.stdout(self.handle.__doc__)
            return 0

        self.stdout("Starting interactive Python shell...")
        self.stdout("Project modules are available for import.")
        self.stdout("Use Ctrl+D or exit() to quit.")
        self.stdout()

        # Set up environment
        os.environ.setdefault("PYTHONPATH", os.getcwd())

        # Prepare startup script
        startup_code = """
# Auto-imported modules for convenience
import asyncio
import os
import sys
from pathlib import Path

# Project imports
try:
    from neutronapi.db import setup_databases, get_databases
    from neutronapi.db.models import Model
    from neutronapi.db.migrations import MigrationManager
    from neutronapi.db.fields import *
    print("✓ Database modules imported")
except ImportError as e:
    print(f"⚠ Could not import database modules: {e}")

print("\\nQuick start:")
print("  setup_databases()  # Initialize databases")
print("  manager = MigrationManager()  # Create migration manager")
print("  await manager.bootstrap_all()  # Bootstrap all apps")
print()
"""

        # Write startup script to a temporary file
        startup_file = "/tmp/neutron_shell_startup.py"
        with open(startup_file, "w") as f:
            f.write(startup_code)

        # Set PYTHONSTARTUP to load our script
        env = os.environ.copy()
        env["PYTHONSTARTUP"] = startup_file

        # Launch Python shell with asyncio support
        try:
            # Try IPython first (nicer interface)
            self.stdout("Starting IPython shell...")
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "IPython", env=env
            )
            rc = await proc.wait()
            if rc != 0:
                # Fallback to regular Python with asyncio
                self.stdout("Starting Python shell with asyncio support...")
                proc2 = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "asyncio", env=env
                )
                await proc2.wait()
        except KeyboardInterrupt:
            self.stdout("\nShell interrupted by user")
        except Exception as e:
            raise CommandError(f"Error starting shell: {e}")
        finally:
            # Clean up startup file
            try:
                os.remove(startup_file)
            except OSError:
                pass
        return 0
