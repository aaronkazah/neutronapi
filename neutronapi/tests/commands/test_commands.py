import os
import shutil
import tempfile
import unittest
from pathlib import Path

import neutronapi.cli as cli
from neutronapi.diagnostics import collect_project_checks
from neutronapi.exceptions import CommandError


class TestCommands(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmpdir = Path(tempfile.mkdtemp(prefix="neutronapi_cmds_"))
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_discover_and_scaffold_project_and_app(self):
        commands = cli.discover_commands()
        self.assertIn("check", commands)
        self.assertIn("startapp", commands)
        self.assertIn("startproject", commands)
        self.assertNotIn("base", commands)

        from neutronapi.commands.startproject import Command as StartProjectCommand

        await StartProjectCommand().handle(["proj"])

        project_root = self.tmpdir / "proj"
        self.assertTrue((project_root / "manage.py").is_file())
        self.assertTrue((project_root / "apps" / "settings.py").is_file())
        self.assertTrue((project_root / "apps" / "entry.py").is_file())

        os.chdir(project_root)
        try:
            result = collect_project_checks()
            self.assertFalse(result.has_errors)

            from neutronapi.conf import get_app_from_entry

            app = get_app_from_entry()
            self.assertIn("main", app.apis)

            from neutronapi.commands.startapp import Command as StartAppCommand

            await StartAppCommand().handle(["blog"])
            self.assertTrue((project_root / "apps" / "blog" / "api.py").is_file())
            self.assertTrue((project_root / "apps" / "blog" / "models.py").is_file())
            self.assertTrue((project_root / "apps" / "blog" / "tests" / "test_blog_api.py").is_file())

            warning_ids = {message.check_id for message in collect_project_checks().warnings}
            self.assertIn("entry.W001", warning_ids)
        finally:
            os.chdir(self.tmpdir)

    async def test_startproject_repairs_missing_files_without_overwriting_local_changes(self):
        from neutronapi.commands.startproject import Command as StartProjectCommand

        await StartProjectCommand().handle(["proj"])

        manage_path = self.tmpdir / "proj" / "manage.py"
        settings_path = self.tmpdir / "proj" / "apps" / "settings.py"
        manage_path.write_text("# local change\n", encoding="utf-8")
        settings_path.unlink()

        await StartProjectCommand().handle(["proj", "proj"])

        self.assertEqual(manage_path.read_text(encoding="utf-8"), "# local change\n")
        self.assertTrue(settings_path.exists())

    async def test_startproject_force_overwrites_scaffold_files(self):
        from neutronapi.commands.startproject import Command as StartProjectCommand

        await StartProjectCommand().handle(["proj"])

        manage_path = self.tmpdir / "proj" / "manage.py"
        manage_path.write_text("# drifted\n", encoding="utf-8")

        await StartProjectCommand().handle(["proj", "proj", "--force"])

        self.assertIn("NEUTRONAPI_SETTINGS_MODULE", manage_path.read_text(encoding="utf-8"))

    async def test_startapp_repairs_missing_files_without_overwriting_local_changes(self):
        from neutronapi.commands.startproject import Command as StartProjectCommand
        from neutronapi.commands.startapp import Command as StartAppCommand

        await StartProjectCommand().handle(["proj"])
        os.chdir(self.tmpdir / "proj")
        try:
            await StartAppCommand().handle(["blog"])
            models_path = self.tmpdir / "proj" / "apps" / "blog" / "models.py"
            api_path = self.tmpdir / "proj" / "apps" / "blog" / "api.py"
            models_path.write_text("# custom models\n", encoding="utf-8")
            api_path.unlink()

            await StartAppCommand().handle(["blog"])

            self.assertEqual(models_path.read_text(encoding="utf-8"), "# custom models\n")
            self.assertTrue(api_path.exists())
        finally:
            os.chdir(self.tmpdir)

    async def test_startproject_rejects_non_project_nonempty_destination(self):
        from neutronapi.commands.startproject import Command as StartProjectCommand

        occupied = self.tmpdir / "occupied"
        occupied.mkdir()
        (occupied / "notes.txt").write_text("not a project\n", encoding="utf-8")

        with self.assertRaises(CommandError):
            await StartProjectCommand().handle(["proj", str(occupied)])

    async def test_name_validation_rejects_reserved_names(self):
        from neutronapi.commands.startproject import Command as StartProjectCommand

        with self.assertRaises(CommandError):
            await StartProjectCommand().handle(["test"])

    async def test_help_functionality(self):
        from neutronapi.commands.startapp import Command as StartAppCommand

        command = StartAppCommand()
        self.assertEqual(command.help, "Create or repair an app scaffold under ./apps.")

        await command.handle(["--help"])

        self.assertFalse((self.tmpdir / "apps" / "--help").exists())
        self.assertFalse((self.tmpdir / "--help").exists())

    async def test_command_without_help(self):
        class MockCommand:
            async def handle(self, args):
                return 0

        mock_cmd = MockCommand()
        self.assertFalse(hasattr(mock_cmd, "help"))
        self.assertEqual(getattr(mock_cmd, "help", "No description available"), "No description available")
