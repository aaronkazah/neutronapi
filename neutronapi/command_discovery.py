from __future__ import annotations

import importlib
import os
import pkgutil
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List


CLI_ONLY_COMMANDS = {"startproject"}
IGNORED_COMMAND_MODULES = {"base"}


@dataclass(frozen=True)
class CommandImportError:
    command_name: str
    module_name: str
    error: str
    source: str


@dataclass
class CommandDiscoveryResult:
    commands: Dict[str, Any] = field(default_factory=dict)
    errors: List[CommandImportError] = field(default_factory=list)

    def merge(self, other: "CommandDiscoveryResult") -> "CommandDiscoveryResult":
        self.commands.update(other.commands)
        self.errors.extend(other.errors)
        return self


def _clear_module(module_name: str) -> None:
    importlib.invalidate_caches()
    parts = module_name.split(".")
    parents: List[str] = []
    while parts:
        parents.append(".".join(parts))
        parts.pop()

    for name in parents:
        sys.modules.pop(name, None)


def _load_command(
    module_name: str,
    command_name: str,
    source: str,
) -> tuple[Any | None, CommandImportError | None]:
    try:
        _clear_module(module_name)
        module = importlib.import_module(module_name)
    except Exception as exc:
        return None, CommandImportError(
            command_name=command_name,
            module_name=module_name,
            error=str(exc),
            source=source,
        )

    command = getattr(module, "Command", None)
    if command is None:
        return None, None
    try:
        return command(), None
    except Exception as exc:
        return None, CommandImportError(
            command_name=command_name,
            module_name=module_name,
            error=str(exc),
            source=source,
        )


def discover_builtin_commands(*, exclude_cli_only: bool = False) -> CommandDiscoveryResult:
    result = CommandDiscoveryResult()
    package = importlib.import_module("neutronapi.commands")
    for _, name, ispkg in pkgutil.iter_modules(package.__path__):
        if ispkg:
            continue
        if name in IGNORED_COMMAND_MODULES:
            continue
        if exclude_cli_only and name in CLI_ONLY_COMMANDS:
            continue
        command, error = _load_command(
            module_name=f"neutronapi.commands.{name}",
            command_name=name,
            source="builtin",
        )
        if error is not None:
            result.errors.append(error)
            continue
        if command is not None:
            result.commands[name] = command
    return result


def discover_project_commands(project_root: str | None = None) -> CommandDiscoveryResult:
    result = CommandDiscoveryResult()
    project_root = os.path.abspath(project_root or os.getcwd())
    apps_dir = os.path.join(project_root, "apps")
    if not os.path.isdir(apps_dir):
        return result

    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    for app_name in sorted(os.listdir(apps_dir)):
        app_path = os.path.join(apps_dir, app_name)
        commands_dir = os.path.join(app_path, "commands")
        if not os.path.isdir(app_path) or app_name.startswith("."):
            continue
        if not os.path.isdir(commands_dir):
            continue

        for filename in sorted(os.listdir(commands_dir)):
            if not filename.endswith(".py") or filename.startswith("__"):
                continue
            command_name = filename[:-3]
            command, error = _load_command(
                module_name=f"apps.{app_name}.commands.{command_name}",
                command_name=command_name,
                source=f"apps.{app_name}",
            )
            if error is not None:
                result.errors.append(error)
                continue
            if command is not None:
                result.commands[command_name] = command
    return result


def discover_all_commands(
    *,
    exclude_cli_only: bool = False,
    project_root: str | None = None,
) -> CommandDiscoveryResult:
    result = discover_builtin_commands(exclude_cli_only=exclude_cli_only)
    result.merge(discover_project_commands(project_root=project_root))
    return result
