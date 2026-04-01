import os
import shutil
import tempfile
import unittest
from pathlib import Path

from neutronapi.diagnostics import collect_project_checks
from neutronapi.scaffold import scaffold_app, scaffold_project


class TestProjectChecks(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmpdir = Path(tempfile.mkdtemp(prefix="neutronapi_checks_"))
        self.project_root = self.tmpdir / "blog"
        scaffold_project("blog", str(self.project_root))
        os.chdir(self.project_root)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _message_ids(self):
        result = collect_project_checks()
        return result, {message.check_id for message in result.messages}

    def test_missing_settings_file(self):
        (self.project_root / "apps" / "settings.py").unlink()
        _, message_ids = self._message_ids()
        self.assertIn("project.E003", message_ids)

    def test_missing_entry_variable(self):
        (self.project_root / "apps" / "settings.py").write_text(
            "DATABASES = {'default': {'ENGINE': 'aiosqlite', 'NAME': 'db.sqlite3'}}\n",
            encoding="utf-8",
        )
        _, message_ids = self._message_ids()
        self.assertIn("settings.E002", message_ids)

    def test_missing_entry_attribute(self):
        (self.project_root / "apps" / "settings.py").write_text(
            "\n".join(
                [
                    "ENTRY = 'apps.entry:missing_app'",
                    "DATABASES = {'default': {'ENGINE': 'aiosqlite', 'NAME': 'db.sqlite3'}}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        _, message_ids = self._message_ids()
        self.assertIn("entry.E003", message_ids)

    def test_missing_api_name(self):
        (self.project_root / "apps" / "entry.py").write_text(
            "\n".join(
                [
                    "from neutronapi.application import Application",
                    "from neutronapi.base import API",
                    "",
                    "class BrokenAPI(API):",
                    '    resource = ""',
                    "",
                    '    @API.endpoint("/", methods=["GET"], name="home")',
                    "    async def home(self, scope, receive, send, **kwargs):",
                    "        return await self.response({'ok': True})",
                    "",
                    "app = Application(apis=[BrokenAPI()])",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        result, message_ids = self._message_ids()
        self.assertIn("api.E002", message_ids)
        self.assertTrue(any("name" in (message.hint or "") for message in result.messages))

    def test_broken_command_import(self):
        commands_dir = self.project_root / "apps" / "blog" / "commands"
        commands_dir.mkdir(parents=True)
        (self.project_root / "apps" / "blog" / "__init__.py").write_text("", encoding="utf-8")
        (commands_dir / "__init__.py").write_text("", encoding="utf-8")
        (commands_dir / "broken.py").write_text("def this is invalid\n", encoding="utf-8")

        _, message_ids = self._message_ids()
        self.assertIn("command.E001", message_ids)

    def test_unregistered_app_api_warning(self):
        scaffold_app("posts", str(self.project_root / "apps" / "posts"))
        _, message_ids = self._message_ids()
        self.assertIn("entry.W001", message_ids)
