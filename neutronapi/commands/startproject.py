"""Create or repair a NeutronAPI project scaffold."""
from __future__ import annotations

from typing import List

from neutronapi.commands.base import BaseCommand
from neutronapi.exceptions import CommandError
from neutronapi.scaffold import format_scaffold_report, scaffold_project


class Command(BaseCommand):
    def __init__(self):
        super().__init__()
        self.help = "Create or repair a NeutronAPI project scaffold."

    async def handle(self, args: List[str]) -> int:
        if not args or any(arg in {"--help", "-h", "help"} for arg in args):
            self.stdout("Usage: neutronapi startproject <project_name> [destination_dir] [--force]")
            self.stdout(self.help)
            return 0

        force = False
        positional: list[str] = []
        for arg in args:
            if arg == "--force":
                force = True
            else:
                positional.append(arg)

        if len(positional) not in {1, 2}:
            raise CommandError("startproject expects a project name and an optional destination.")

        project_name = positional[0]
        destination = positional[1] if len(positional) == 2 else project_name

        result = scaffold_project(project_name, destination, force=force)
        self.stdout(format_scaffold_report(f"Project '{project_name}'", result, force=force))
        self.stdout("Next steps:")
        self.stdout(f"  cd {result.destination}")
        self.stdout("  python manage.py check")
        self.stdout("  python manage.py start --no-reload")
        self.stdout("  python manage.py test")
        return 0
