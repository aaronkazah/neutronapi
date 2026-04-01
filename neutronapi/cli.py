"""NeutronAPI command-line entrypoint."""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
from typing import Any, Dict

from neutronapi.command_discovery import discover_all_commands
from neutronapi.conf import is_neutronapi_development
from neutronapi.diagnostics import run_project_checks
from neutronapi.exceptions import CommandError
from neutronapi.scaffold import ensure_project_root


AUTO_CHECK_COMMANDS = {"migrate", "makemigrations", "shell", "start", "test"}
PROJECT_COMMANDS = AUTO_CHECK_COMMANDS | {"check", "startapp"}


def _running_via_manage_py() -> bool:
    return os.path.basename(sys.argv[0]) == "manage.py"


def discover_commands() -> Dict[str, Any]:
    return discover_all_commands().commands


def _print_command_list(commands: Dict[str, Any]) -> None:
    print("Available commands:")
    for command_name in sorted(commands):
        command = commands[command_name]
        help_text = getattr(command, "help", "No description available").splitlines()[0]
        print(f"  {command_name:<15} {help_text}")
    print("\nUse 'neutronapi <command> --help' for detailed usage")


def _coerce_command_result(result: Any) -> int:
    return result if isinstance(result, int) else 0


def _invoke_handle(command: Any, args: list[str]):
    handle = getattr(command, "handle", None)
    if handle is None:
        raise CommandError(f"Command '{command.__class__.__name__}' is missing handle().")

    signature = inspect.signature(handle)
    parameters = list(signature.parameters.values())
    if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
        return handle(*args)
    if not parameters:
        return handle()
    return handle(args)


async def _run_command(command_name: str, command: Any, args: list[str]) -> int:
    result = _invoke_handle(command, args)
    if inspect.isawaitable(result):
        result = await result
    return _coerce_command_result(result)


async def _shutdown_connections() -> None:
    try:
        from neutronapi.db import shutdown_all_connections

        await asyncio.wait_for(shutdown_all_connections(), timeout=5)
    except asyncio.TimeoutError:
        print("Warning: database shutdown timed out.")
    except Exception:
        pass


def _require_project(command_name: str) -> None:
    if command_name not in PROJECT_COMMANDS:
        return
    if command_name == "check":
        return
    try:
        ensure_project_root(os.getcwd())
    except CommandError:
        if command_name in AUTO_CHECK_COMMANDS and is_neutronapi_development():
            return
        raise


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    discovery = discover_all_commands(exclude_cli_only=_running_via_manage_py())
    commands = discovery.commands

    if not argv:
        _print_command_list(commands)
        return 0

    command_name = argv[0]
    args = argv[1:]

    if command_name in {"--help", "-h", "help"}:
        _print_command_list(commands)
        return 0

    if command_name not in commands:
        matching_error = next(
            (error for error in discovery.errors if error.command_name == command_name),
            None,
        )
        if matching_error is not None:
            print(
                f"Error: Command '{command_name}' could not be loaded from "
                f"'{matching_error.module_name}'."
            )
            print(f"HINT: {matching_error.error}")
        else:
            print(f"Unknown command: {command_name}")
            print("Available commands:", ", ".join(sorted(commands.keys())))
        return 1

    skip_checks = False
    if "--skip-checks" in args:
        skip_checks = True
        args = [arg for arg in args if arg != "--skip-checks"]

    try:
        _require_project(command_name)

        if command_name in AUTO_CHECK_COMMANDS and not skip_checks:
            check_exit = run_project_checks(quiet=True)
            if check_exit != 0:
                return check_exit

        return asyncio.run(_run_command(command_name, commands[command_name], args))
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        return 1
    except CommandError as exc:
        print(f"Error: {exc}")
        return 1
    except Exception as exc:
        print(f"Error while running '{command_name}': {exc}")
        if os.getenv("DEBUG", "false").lower() == "true":
            import traceback

            traceback.print_exc()
        return 1
    finally:
        asyncio.run(_shutdown_connections())


if __name__ == "__main__":
    raise SystemExit(main())
