from __future__ import annotations

import keyword
import os
import stat
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable

from neutronapi.exceptions import CommandError


PROJECT_CANONICAL_FILES = (
    "manage.py",
    "apps/__init__.py",
    "apps/settings.py",
    "apps/entry.py",
)

APP_CANONICAL_FILES = (
    "__init__.py",
    "api.py",
    "models.py",
    "migrations/__init__.py",
    "commands/__init__.py",
    "tests/__init__.py",
)

RESERVED_NAMES = {
    "django",
    "neutronapi",
    "test",
}


@dataclass
class ScaffoldResult:
    destination: str
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    drifted: list[str] = field(default_factory=list)


def validate_scaffold_name(name: str, *, kind: str) -> None:
    if not name:
        raise CommandError(f"{kind.capitalize()} name is required.")
    if not name.isidentifier():
        raise CommandError(
            f"{kind.capitalize()} name '{name}' is invalid. Use a valid Python identifier."
        )
    if keyword.iskeyword(name):
        raise CommandError(
            f"{kind.capitalize()} name '{name}' is invalid. Python keywords are not allowed."
        )
    if name.lower() in RESERVED_NAMES:
        raise CommandError(
            f"{kind.capitalize()} name '{name}' is reserved. Choose a different name."
        )


def is_neutronapi_project(path: str | os.PathLike[str]) -> bool:
    root = Path(path)
    apps_dir = root / "apps"
    return apps_dir.is_dir() and any((root / rel_path).exists() for rel_path in PROJECT_CANONICAL_FILES)


def is_neutronapi_app(path: str | os.PathLike[str]) -> bool:
    root = Path(path)
    if not root.is_dir():
        return False
    return any((root / rel_path).exists() for rel_path in APP_CANONICAL_FILES)


def render_project_files(project_name: str) -> Dict[str, str]:
    manage_py = textwrap.dedent(
        """\
        #!/usr/bin/env python3
        import os
        import sys


        def main() -> int:
            os.environ.setdefault("NEUTRONAPI_SETTINGS_MODULE", "apps.settings")
            from neutronapi.cli import main as cli_main

            return cli_main()


        if __name__ == "__main__":
            raise SystemExit(main())
        """
    )

    settings_py = textwrap.dedent(
        f"""\
        \"\"\"Settings for the {project_name} project.\"\"\"
        import os
        from pathlib import Path


        BASE_DIR = Path(__file__).resolve().parent.parent
        ENTRY = "apps.entry:app"

        DATABASES = {{
            "default": {{
                "ENGINE": "aiosqlite",
                "NAME": ":memory:" if os.getenv("TESTING") == "1" else BASE_DIR / "db.sqlite3",
            }}
        }}

        SECRET_KEY = os.getenv("SECRET_KEY", "dev-key-change-me")
        DEBUG = os.getenv("DEBUG", "true").lower() == "true"
        ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
        USE_TZ = True
        TIME_ZONE = "UTC"
        """
    )

    entry_py = textwrap.dedent(
        f"""\
        \"\"\"ASGI entrypoint for the {project_name} project.\"\"\"
        from neutronapi.application import Application
        from neutronapi.base import API


        class MainAPI(API):
            resource = ""
            name = "main"

            @API.endpoint("/", methods=["GET"], name="home")
            async def home(self, scope, receive, send, **kwargs):
                return await self.response({{"message": "Hello from {project_name}!"}})


        app = Application(
            apis=[
                MainAPI(),
            ],
        )
        """
    )

    return {
        "manage.py": manage_py,
        "apps/__init__.py": "",
        "apps/settings.py": settings_py,
        "apps/entry.py": entry_py,
    }


def render_app_files(app_name: str) -> Dict[str, str]:
    class_name = "".join(part.capitalize() for part in app_name.rstrip("s").split("_") if part) or "App"
    resource = f"/{app_name}"
    api_name = f"{class_name}API"
    model_name = f"{class_name}Record"
    test_path = f"tests/test_{app_name}_api.py"

    api_py = textwrap.dedent(
        f"""\
        from neutronapi.base import API


        class {api_name}(API):
            resource = "{resource}"
            name = "{app_name}"

            @API.endpoint("/", methods=["GET"], name="list")
            async def list_items(self, scope, receive, send, **kwargs):
                return await self.response([])
        """
    )

    models_py = textwrap.dedent(
        f"""\
        from neutronapi.db.fields import CharField
        from neutronapi.db.models import Model


        class {model_name}(Model):
            name = CharField(max_length=255)
        """
    )

    tests_py = textwrap.dedent(
        f"""\
        import unittest

        from apps.{app_name}.api import {api_name}


        class {api_name}Tests(unittest.TestCase):
            def test_api_metadata(self):
                api = {api_name}()
                self.assertEqual(api.name, "{app_name}")
                self.assertEqual(api.resource, "{resource}")
        """
    )

    return {
        "__init__.py": "",
        "api.py": api_py,
        "models.py": models_py,
        "migrations/__init__.py": "",
        "commands/__init__.py": "",
        "tests/__init__.py": "",
        test_path: tests_py,
    }


def _write_scaffold_files(
    destination: Path,
    rendered_files: Dict[str, str],
    *,
    force: bool,
) -> ScaffoldResult:
    result = ScaffoldResult(destination=str(destination))
    for relative_path, content in rendered_files.items():
        file_path = destination / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_content = content if content.endswith("\n") or not content else f"{content}\n"

        if not file_path.exists():
            file_path.write_text(normalized_content, encoding="utf-8")
            result.created.append(relative_path)
            continue

        current_content = file_path.read_text(encoding="utf-8")
        if current_content == normalized_content:
            result.unchanged.append(relative_path)
            continue

        if force:
            file_path.write_text(normalized_content, encoding="utf-8")
            result.updated.append(relative_path)
        else:
            result.drifted.append(relative_path)

    manage_path = destination / "manage.py"
    if manage_path.exists():
        manage_path.chmod(manage_path.stat().st_mode | stat.S_IXUSR)
    return result


def _validate_destination(
    destination: Path,
    *,
    recognized: bool,
) -> None:
    if not destination.exists():
        return
    if not destination.is_dir():
        raise CommandError(f"Destination '{destination}' must be a directory.")
    contents = list(destination.iterdir())
    if not contents:
        return
    if recognized:
        return
    raise CommandError(
        f"Destination '{destination}' already exists and is not a NeutronAPI scaffold. "
        "Use an empty directory or an existing NeutronAPI project."
    )


def scaffold_project(project_name: str, destination: str, *, force: bool = False) -> ScaffoldResult:
    validate_scaffold_name(project_name, kind="project")
    dest = Path(destination).resolve()
    recognized = is_neutronapi_project(dest)
    _validate_destination(dest, recognized=recognized)
    dest.mkdir(parents=True, exist_ok=True)
    return _write_scaffold_files(dest, render_project_files(project_name), force=force)


def scaffold_app(
    app_name: str,
    destination: str,
    *,
    force: bool = False,
) -> ScaffoldResult:
    validate_scaffold_name(app_name, kind="app")
    dest = Path(destination).resolve()
    recognized = is_neutronapi_app(dest)
    _validate_destination(dest, recognized=recognized)
    dest.mkdir(parents=True, exist_ok=True)
    return _write_scaffold_files(dest, render_app_files(app_name), force=force)


def format_scaffold_report(label: str, result: ScaffoldResult, *, force: bool) -> str:
    lines = [f"{label} scaffold ready at '{result.destination}'."]
    for heading, values in (
        ("Created", result.created),
        ("Updated", result.updated),
        ("Unchanged", result.unchanged),
        ("Skipped (existing local changes)", result.drifted),
    ):
        if not values:
            continue
        lines.append(f"{heading}:")
        lines.extend(f"  - {value}" for value in values)
    if result.drifted and not force:
        lines.append("Re-run with --force to overwrite scaffold-managed files.")
    return "\n".join(lines)


def ensure_project_root(path: str | os.PathLike[str]) -> Path:
    root = Path(path).resolve()
    if not is_neutronapi_project(root):
        raise CommandError(
            f"'{root}' is not a NeutronAPI project. "
            "Expected manage.py plus the apps/ scaffold."
        )
    return root


def ensure_app_destination(project_root: Path, app_name: str, destination: str | None) -> Path:
    if destination is None:
        return (project_root / "apps" / app_name).resolve()

    target = Path(destination).resolve()
    apps_root = (project_root / "apps").resolve()
    try:
        target.relative_to(apps_root)
    except ValueError as exc:
        raise CommandError(
            f"App destination '{target}' must live under '{apps_root}'."
        ) from exc
    return target
