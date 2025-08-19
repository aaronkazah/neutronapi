"""
Django-style migrate command.
Apply database migrations.
"""
import asyncio
import os
from typing import List


class Command:
    """Django-style migrate command class."""

    def __init__(self):
        self.help = "Apply database migrations"

    async def handle(self, args: List[str]) -> None:
        """
        Apply database migrations.
        
        Usage:
            python manage.py migrate                # Apply all pending migrations
            python manage.py migrate app_name       # Apply migrations for specific app
            python manage.py migrate --help         # Show help
        
        Examples:
            python manage.py migrate
            python manage.py migrate core
            python manage.py migrate my_app
        """
        
        # Show help if requested
        if args and args[0] in ["--help", "-h", "help"]:
            print(f"{self.help}\n")
            print(self.handle.__doc__)
            return
        
        print("Applying database migrations...")
        
        try:
            from neutronapi.db.migrations import MigrationManager
            from neutronapi.db import setup_databases
            # Use Django-style settings for configuration
            try:
                from apps.settings import DATABASES
            except Exception:
                DATABASES = None
            
            # Setup databases (only override if settings provided)
            if DATABASES:
                setup_databases(DATABASES)
            
            # Determine which apps to migrate
            if args:
                apps = args
                print(f"Migrating apps: {', '.join(apps)}")
            else:
                # Auto-discover apps
                apps = None
                print("Auto-discovering and migrating all apps...")
            
            # Create migration manager
            manager = MigrationManager(apps=apps, base_dir="apps")
            
            # Run migrations
            processed_count = await manager.bootstrap_all(test_mode=False)
            
            if processed_count > 0:
                print(f"✓ Migrations applied successfully for {processed_count} app(s)!")
            else:
                print("No migrations needed - all apps are up to date.")
            
        except ImportError as e:
            print(f"Error: Could not import migration modules: {e}")
            print("Make sure the database modules are properly installed.")
            return
        except Exception as e:
            print(f"Error applying migrations: {e}")
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
