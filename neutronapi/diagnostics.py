from __future__ import annotations

import importlib
import inspect
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List

from neutronapi.command_discovery import discover_all_commands
from neutronapi.conf import DEFAULT_SETTINGS_MODULE, is_neutronapi_development
from neutronapi.scaffold import PROJECT_CANONICAL_FILES

logger = logging.getLogger('neutronapi.diagnostics')


@dataclass(frozen=True)
class CheckMessage:
    level: str
    check_id: str
    message: str
    hint: str = ""


@dataclass
class CheckResult:
    messages: List[CheckMessage] = field(default_factory=list)

    @property
    def errors(self) -> List[CheckMessage]:
        return [message for message in self.messages if message.level == "ERROR"]

    @property
    def warnings(self) -> List[CheckMessage]:
        return [message for message in self.messages if message.level == "WARNING"]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


def _project_root(path: str | None = None) -> Path:
    return Path(path or os.getcwd()).resolve()


def _add_project_to_path(project_root: Path) -> None:
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


def _clear_module(module_name: str) -> None:
    importlib.invalidate_caches()
    parts = module_name.split(".")
    parents: list[str] = []
    while parts:
        parents.append(".".join(parts))
        parts.pop()
    for name in parents:
        sys.modules.pop(name, None)


def _import_module(module_name: str):
    _clear_module(module_name)
    return importlib.import_module(module_name)


def _should_skip_project_layout(project_root: Path) -> bool:
    settings_path = project_root / "apps" / "settings.py"
    return is_neutronapi_development(str(project_root)) and not settings_path.exists()


def _validate_project_files(project_root: Path, result: CheckResult) -> None:
    if _should_skip_project_layout(project_root):
        return

    file_checks = (
        ("project.E001", "manage.py"),
        ("project.E002", "apps/__init__.py"),
        ("project.E003", "apps/settings.py"),
        ("project.E004", "apps/entry.py"),
    )
    for check_id, relative_path in file_checks:
        if not (project_root / relative_path).exists():
            result.messages.append(
                CheckMessage(
                    level="ERROR",
                    check_id=check_id,
                    message=f"Required file '{relative_path}' is missing.",
                    hint="Repair the project scaffold with `python -m neutronapi startproject <name> .`.",
                )
            )


def _validate_settings(project_root: Path, result: CheckResult) -> tuple[object | None, str | None]:
    if any(message.check_id in {"project.E003", "project.E004"} for message in result.errors):
        return None, None
    if _should_skip_project_layout(project_root):
        return None, None

    settings_module_name = os.environ.get("NEUTRONAPI_SETTINGS_MODULE", DEFAULT_SETTINGS_MODULE)
    _add_project_to_path(project_root)

    try:
        settings_module = _import_module(settings_module_name)
    except Exception as exc:
        result.messages.append(
            CheckMessage(
                level="ERROR",
                check_id="settings.E001",
                message=f"Could not import settings module '{settings_module_name}'.",
                hint=str(exc),
            )
        )
        return None, None

    if not hasattr(settings_module, "ENTRY"):
        result.messages.append(
            CheckMessage(
                level="ERROR",
                check_id="settings.E002",
                message="The settings module is missing the required 'ENTRY' variable.",
                hint="Define ENTRY as 'module:variable', for example 'apps.entry:app'.",
            )
        )
        return settings_module, None

    databases = getattr(settings_module, "DATABASES", None)
    if databases is None:
        result.messages.append(
            CheckMessage(
                level="ERROR",
                check_id="settings.E003",
                message="The settings module is missing the required 'DATABASES' variable.",
                hint="Define DATABASES with at least a 'default' connection.",
            )
        )
    elif not isinstance(databases, dict):
        result.messages.append(
            CheckMessage(
                level="ERROR",
                check_id="settings.E004",
                message="DATABASES must be a dictionary.",
            )
        )
    else:
        default = databases.get("default")
        if not isinstance(default, dict):
            result.messages.append(
                CheckMessage(
                    level="ERROR",
                    check_id="settings.E005",
                    message="DATABASES must contain a 'default' database dictionary.",
                )
            )
        else:
            for key, check_id in (("ENGINE", "settings.E006"), ("NAME", "settings.E007")):
                if key not in default:
                    result.messages.append(
                        CheckMessage(
                            level="ERROR",
                            check_id=check_id,
                            message=f"DATABASES['default'] is missing '{key}'.",
                        )
                    )

    return settings_module, getattr(settings_module, "ENTRY", None)


def _validate_entry(project_root: Path, entry_value: str | None, result: CheckResult) -> object | None:
    if not entry_value:
        return None
    if ":" not in entry_value:
        result.messages.append(
            CheckMessage(
                level="ERROR",
                check_id="entry.E001",
                message=f"ENTRY '{entry_value}' is invalid.",
                hint="Use the form 'module:variable', for example 'apps.entry:app'.",
            )
        )
        return None

    module_name, attr_name = entry_value.split(":", 1)
    _add_project_to_path(project_root)

    try:
        module = _import_module(module_name)
    except Exception as exc:
        error_text = str(exc)
        if "must have a 'name' attribute" in error_text:
            result.messages.append(
                CheckMessage(
                    level="ERROR",
                    check_id="api.E002",
                    message=f"API registration failed while importing '{module_name}'.",
                    hint=error_text,
                )
            )
            return None
        result.messages.append(
            CheckMessage(
                level="ERROR",
                check_id="entry.E002",
                message=f"Could not import entry module '{module_name}'.",
                hint=error_text,
            )
        )
        return None

    if not hasattr(module, attr_name):
        result.messages.append(
            CheckMessage(
                level="ERROR",
                check_id="entry.E003",
                message=f"Entry module '{module_name}' is missing '{attr_name}'.",
            )
        )
        return None

    try:
        app = getattr(module, attr_name)
    except Exception as exc:
        result.messages.append(
            CheckMessage(
                level="ERROR",
                check_id="entry.E004",
                message=f"Could not resolve '{attr_name}' from '{module_name}'.",
                hint=str(exc),
            )
        )
        return None

    if not callable(app):
        result.messages.append(
            CheckMessage(
                level="ERROR",
                check_id="entry.E005",
                message=f"ENTRY target '{entry_value}' is not callable.",
                hint="NeutronAPI expects an ASGI application or Application instance.",
            )
        )
        return None

    return app


def _discover_api_classes(module_name: str) -> Iterable[type]:
    from neutronapi.base import API

    module = _import_module(module_name)
    api_classes = []
    for _, member in inspect.getmembers(module, inspect.isclass):
        if member is API or not issubclass(member, API):
            continue
        if member.__module__ != module.__name__:
            continue
        api_classes.append(member)
    return api_classes


def _validate_app_integration(project_root: Path, app: object | None, result: CheckResult) -> None:
    apps_dir = project_root / "apps"
    if app is None or not apps_dir.is_dir():
        return

    registered_classes = {
        api_instance.__class__
        for api_instance in getattr(app, "apis", {}).values()
    }
    for app_dir in sorted(apps_dir.iterdir()):
        if not app_dir.is_dir() or app_dir.name.startswith("."):
            continue
        api_module_path = app_dir / "api.py"
        if not api_module_path.exists():
            continue

        module_name = f"apps.{app_dir.name}.api"
        try:
            api_classes = list(_discover_api_classes(module_name))
        except Exception as exc:
            result.messages.append(
                CheckMessage(
                    level="ERROR",
                    check_id="api.E001",
                    message=f"Could not import app API module '{module_name}'.",
                    hint=str(exc),
                )
            )
            continue

        for api_class in api_classes:
            if getattr(api_class, "name", None) in {None, ""}:
                result.messages.append(
                    CheckMessage(
                        level="ERROR",
                        check_id="api.E002",
                        message=f"API '{module_name}.{api_class.__name__}' is missing 'name'.",
                        hint="Define a unique API.name so reverse lookups and registration succeed.",
                    )
                )
            if api_class not in registered_classes:
                result.messages.append(
                    CheckMessage(
                        level="WARNING",
                        check_id="entry.W001",
                        message=f"API '{module_name}.{api_class.__name__}' is not registered in apps.entry.",
                        hint=f"Import {api_class.__name__} in apps.entry and add `{api_class.__name__}()` to Application(apis=[...]).",
                    )
                )


def _validate_command_imports(project_root: Path, result: CheckResult) -> None:
    discovery = discover_all_commands(project_root=str(project_root))
    for error in discovery.errors:
        result.messages.append(
            CheckMessage(
                level="ERROR",
                check_id="command.E001",
                message=f"Could not import command '{error.command_name}' from '{error.module_name}'.",
                hint=error.error,
            )
        )


def collect_project_checks(project_root: str | None = None) -> CheckResult:
    root = _project_root(project_root)
    result = CheckResult()

    _validate_project_files(root, result)
    _, entry_value = _validate_settings(root, result)
    app = _validate_entry(root, entry_value, result)
    _validate_app_integration(root, app, result)
    _validate_command_imports(root, result)
    return result


def print_check_report(result: CheckResult, *, quiet: bool = False) -> None:
    for message in result.messages:
        if message.level == "ERROR":
            logger.warning(f"{message.level} {message.check_id}: {message.message}")
        else:
            logger.info(f"{message.level} {message.check_id}: {message.message}")
        if message.hint:
            logger.info(f"HINT: {message.hint}")

    if quiet and not result.messages:
        return

    if result.has_errors:
        logger.info(
            f"System check identified {len(result.messages)} issue(s) "
            f"({len(result.errors)} errors, {len(result.warnings)} warnings)."
        )
    elif result.warnings:
        logger.info(
            f"System check identified {len(result.warnings)} warning(s) and no blocking errors."
        )
    else:
        logger.info("System check identified no issues.")


def run_project_checks(*, quiet: bool = False) -> int:
    result = collect_project_checks()
    print_check_report(result, quiet=quiet)
    return 1 if result.has_errors else 0
