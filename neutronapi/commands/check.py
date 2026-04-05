from __future__ import annotations

from typing import List

from neutronapi.commands.base import BaseCommand
from neutronapi.diagnostics import run_project_checks


class Command(BaseCommand):
    def __init__(self):
        super().__init__()
        self.help = "Run project system checks."

    async def handle(self, args: List[str]) -> int:
        if any(arg in {"--help", "-h", "help"} for arg in args):
            self.stdout("Usage: python manage.py check [--quiet]")
            self.stdout(self.help)
            return 0

        quiet = "--quiet" in args
        return run_project_checks(quiet=quiet)
