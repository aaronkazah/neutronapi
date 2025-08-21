"""
Interactive shell command.
Launch an interactive Python shell with project context.
"""
import os
import sys
import asyncio
from typing import List


class Command:
    """Interactive shell command class."""

    def __init__(self):
        self.help = "Launch an interactive Python shell with the project initialized"

    async def handle(self, args: List[str]) -> None:
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
            print(f"{self.help}\n")
            print(self.handle.__doc__)
            return

        print("Starting interactive Python shell...")
        print("Project modules are available for import.")
        print("Use Ctrl+D or exit() to quit.")
        print()

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
            print("Starting IPython shell...")
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "IPython", env=env
            )
            rc = await proc.wait()
            if rc != 0:
                # Fallback to regular Python with asyncio
                print("Starting Python shell with asyncio support...")
                proc2 = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "asyncio", env=env
                )
                await proc2.wait()
        except KeyboardInterrupt:
            print("\nShell interrupted by user")
        except Exception as e:
            print(f"Error starting shell: {e}")
        finally:
            # Clean up startup file
            try:
                os.remove(startup_file)
            except OSError:
                pass
