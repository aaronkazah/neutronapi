"""
Create new migration files by detecting model changes.

Usage:
  python manage.py makemigrations            # All apps
  python manage.py makemigrations <app>     # Specific app
  python manage.py makemigrations --help    # Help
"""
from __future__ import annotations

import os
from typing import List


class Command:
    def __init__(self):
        self.help = "Detect model changes and write numbered migration files (0001_*.py, 0002_*.py, ...)"

    async def handle(self, args: List[str]) -> None:
        """Create new migrations based on changes detected to your models.

        Examples:
          python manage.py makemigrations
          python manage.py makemigrations core
        """
        # Show help if requested
        if args and args[0] in {"--help", "-h", "help"}:
            print(f"{self.help}\n")
            print(self.handle.__doc__)
            return

        try:
            # Import here to avoid import-time project requirements
            from neutronapi.db.migrations import MigrationManager

            # Load optional project DB settings (not strictly needed for makemigrations)
            try:
                from apps.settings import DATABASES  # noqa: F401
            except Exception:
                DATABASES = None  # noqa: F841

            manager = MigrationManager(base_dir="apps")
            app_labels = [args[0]] if args else manager.apps

            any_changes = False
            for app_label in app_labels:
                models = manager._discover_models(app_label)
                if not models:
                    # Quietly skip apps without models
                    continue

                # Write migration file if changes exist
                operations = await manager.makemigrations(
                    app_label=app_label,
                    models=models,
                    return_ops=False,
                    clean=False,
                )
                # When return_ops=False:
                #  - returns operations list if changes were detected (file written)
                #  - returns None if no changes
                if operations is not None:
                    any_changes = True

            if not any_changes:
                print("No changes detected")

        except ImportError as e:
            print(f"Error: Unable to import migration modules: {e}")
        except Exception as e:
            print(f"Error creating migrations: {e}")
            if os.getenv("DEBUG", "False").lower() == "true":
                import traceback
                traceback.print_exc()
