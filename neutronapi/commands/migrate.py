"""
File-based migrate command with hash tracking.
Apply database migrations from numbered files.
"""
import os
from typing import List, Optional

from neutronapi.exceptions import CommandError


class Command:
    """File-based migrate command class."""

    def __init__(self):
        self.help = "Apply database migrations from numbered files (001_initial.py, 002_add_users.py, etc.)"

    def _parse_args(self, args: List[str]) -> tuple:
        """Parse command arguments.
        
        Returns:
            tuple: (database_alias, show_migrations, show_help)
                   database_alias is None to migrate all databases
        """
        database_alias: Optional[str] = None
        show_migrations = False
        show_help = False
        
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in ["--help", "-h", "help"]:
                show_help = True
            elif arg == "--show":
                show_migrations = True
            elif arg == "--database":
                if i + 1 < len(args):
                    database_alias = args[i + 1]
                    i += 1
            elif arg.startswith("--database="):
                database_alias = arg.split("=", 1)[1]
            i += 1
        
        return database_alias, show_migrations, show_help

    async def handle(self, args: List[str]) -> int:
        """
        Apply database migrations from numbered migration files.

        Usage:
            python manage.py migrate                        # Apply migrations to ALL databases
            python manage.py migrate --database default     # Apply migrations to specific database
            python manage.py migrate --database=mydb        # Alternative syntax
            python manage.py migrate --show                 # Show all discovered migrations
            python manage.py migrate --help                 # Show help

        Migration files should be named like:
            apps/core/migrations/001_initial.py
            apps/core/migrations/002_add_users.py
            apps/blog/migrations/001_initial.py

        The system tracks applied migrations by file hash - if you modify a migration
        file, it will be re-applied automatically.

        Each database maintains its own migration tracking table (neutronapi_migrations).

        Examples:
            python manage.py migrate                        # Apply to all databases
            python manage.py migrate --database default     # Apply to 'default' only
            python manage.py migrate --database secondary   # Apply to 'secondary' only
            python manage.py migrate --show                 # List all migration files
        """
        database_alias, show_migrations, show_help = self._parse_args(args)

        # Show help if requested
        if show_help:
            print(f"{self.help}\n")
            print(self.handle.__doc__)
            return 0

        try:
            from neutronapi.db.migration_tracker import MigrationTracker
            from neutronapi.db import setup_databases
            from neutronapi.db.connection import get_databases
            from neutronapi.conf import settings

            # Use settings for configuration
            try:
                databases = settings.DATABASES
            except AttributeError:
                databases = None

            # Setup databases (only override if settings provided)
            if databases:
                setup_databases(databases)

            # Create migration tracker
            tracker = MigrationTracker(base_dir="apps")

            # Handle --show option
            if show_migrations:
                print("Discovered migration files:")
                tracker.show_migrations()
                return

            # Determine which databases to migrate
            db_manager = get_databases()
            if database_alias:
                # Migrate specific database
                db_aliases = [database_alias]
            else:
                # Migrate ALL databases in config
                db_aliases = list(db_manager.config.keys())

            print("Scanning for migration files...")

            # Migrate each database
            for alias in db_aliases:
                print(f"\n{'='*50}")
                print(f"Migrating database: {alias}")
                print(f"{'='*50}")
                
                connection = await db_manager.get_connection(alias)
                try:
                    await tracker.migrate(connection)
                finally:
                    await connection.close()

        except ImportError as e:
            raise CommandError(
                f"Could not import migration modules: {e}. "
                "Make sure the database modules are installed."
            )
        except Exception as e:
            raise CommandError(f"Error applying migrations: {e}")
        finally:
            # Ensure all async DB connections are closed so the event loop can exit
            try:
                from neutronapi.db.connection import get_databases
                await get_databases().close_all()
            except Exception:
                # Don't block shutdown on close errors
                pass
        return 0
