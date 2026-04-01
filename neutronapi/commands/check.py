from __future__ import annotations

from typing import List

from neutronapi.diagnostics import run_project_checks


class Command:
    def __init__(self):
        self.help = "Run project system checks."

    async def handle(self, args: List[str]) -> int:
        if any(arg in {"--help", "-h", "help"} for arg in args):
            print("Usage: python manage.py check [--quiet]")
            print(self.help)
            return 0

        quiet = "--quiet" in args
        return run_project_checks(quiet=quiet)
