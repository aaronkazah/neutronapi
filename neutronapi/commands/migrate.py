"""
File-based migrate command with hash tracking.
Apply database migrations from numbered files.
"""
import os
from typing import List


class Command:
    """File-based migrate command class."""

    def __init__(self):
        self.help = "Apply database migrations from numbered files (001_initial.py, 002_add_users.py, etc.)"

    async def handle(self, args: List[str]) -> None:
        """
        Apply database migrations from numbered migration files.

        Usage:
            python manage.py migrate                # Apply all pending migrations
            python manage.py migrate --show         # Show all discovered migrations
            python manage.py migrate --help         # Show help

        Migration files should be named like:
            apps/core/migrations/001_initial.py
            apps/core/migrations/002_add_users.py
            apps/blog/migrations/001_initial.py

        The system tracks applied migrations by file hash - if you modify a migration
        file, it will be re-applied automatically.

        Examples:
            python manage.py migrate               # Apply all migrations
            python manage.py migrate --show        # List all migration files
        """

        # Show help if requested
        if args and args[0] in ["--help", "-h", "help"]:
            print(f"{self.help}\n")
            print(self.handle.__doc__)
            return

        try:
            from neutronapi.db.migration_tracker import MigrationTracker
            from neutronapi.db import setup_databases
            from neutronapi.db.connection import get_databases

            # Use settings for configuration
            try:
                from apps.settings import DATABASES
            except Exception:
                DATABASES = None

            # Setup databases (only override if settings provided)
            if DATABASES:
                setup_databases(DATABASES)

            # Create migration tracker
            tracker = MigrationTracker(base_dir="apps")

            # Handle --show option
            if args and args[0] == "--show":
                print("Discovered migration files:")
                tracker.show_migrations()
                return

            # Get database connection
            connection = await get_databases().get_connection('default')

            try:
                print("Scanning for migration files...")

                # Run migrations
                await tracker.migrate(connection)

            finally:
                await connection.close()

        except ImportError as e:
            print(f"Error: Could not import migration modules: {e}")
            print("Make sure the database modules are properly installed.")
            return
        except Exception as e:
            print(f"Error applying migrations: {e}")
            import traceback
            traceback.print_exc()
            if os.getenv("DEBUG", "False").lower() == "true":
                import traceback
                traceback.print_exc()
            return
        finally:
            # Ensure all async DB connections are closed so the event loop can exit
            try:
                from neutronapi.db.connection import get_databases
                await get_databases().close_all()
            except Exception:
                # Don't block shutdown on close errors
                pass
