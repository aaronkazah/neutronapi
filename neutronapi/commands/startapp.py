"""Create or repair an app scaffold under ./apps."""
from __future__ import annotations

import os
from typing import List

from neutronapi.exceptions import CommandError
from neutronapi.scaffold import (
    ensure_app_destination,
    ensure_project_root,
    format_scaffold_report,
    scaffold_app,
)


class Command:
    def __init__(self):
        self.help = "Create or repair an app scaffold under ./apps."

    async def handle(self, args: List[str]) -> int:
        if not args or any(arg in {"--help", "-h", "help"} for arg in args):
            print("Usage: python manage.py startapp <app_name> [apps/<app_dir>] [--force]")
            print(self.help)
            return 0

        force = False
        positional: list[str] = []
        for arg in args:
            if arg == "--force":
                force = True
            else:
                positional.append(arg)

        if len(positional) not in {1, 2}:
            raise CommandError("startapp expects an app name and an optional destination under apps/.")

        app_name = positional[0]
        project_root = ensure_project_root(os.getcwd())
        destination = ensure_app_destination(
            project_root,
            app_name,
            positional[1] if len(positional) == 2 else None,
        )

        result = scaffold_app(app_name, str(destination), force=force)
        print(format_scaffold_report(f"App '{app_name}'", result, force=force))
        print("Next steps:")
        print(f"  Wire apps.{app_name}.api into apps.entry")
        print("  python manage.py check")
        print("  python manage.py test")
        return 0
