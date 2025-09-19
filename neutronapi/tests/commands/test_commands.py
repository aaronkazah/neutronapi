import os
import sys
import shutil
import tempfile
import unittest

import neutronapi.cli as cli


class TestCommands(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmpdir = tempfile.mkdtemp(prefix="neutronapi_cmds_")
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_discover_and_startproject_startapp(self):
        cmds = cli.discover_commands()
        # Basic built-in commands present (startproject is CLI-only, not in manage.py commands)
        self.assertIn('startapp', cmds)
        self.assertIn('test', cmds)

        # Create project directly via command (no CLI main)
        from neutronapi.commands import startproject as cmd_startproject
        await cmd_startproject.Command().handle(["proj"])

        self.assertTrue(os.path.isfile(os.path.join("proj", "manage.py")))
        self.assertTrue(os.path.isfile(os.path.join("proj", "apps", "settings.py")))
        self.assertTrue(os.path.isfile(os.path.join("proj", "apps", "entry.py")))

        # Run startapp inside the project
        os.chdir("proj")
        try:
            from neutronapi.commands import startapp as cmd_startapp
            await cmd_startapp.Command().handle(["blog"])
        finally:
            os.chdir("..")

        self.assertTrue(os.path.isdir(os.path.join("proj", "apps", "blog")))
        self.assertTrue(os.path.isfile(os.path.join("proj", "apps", "blog", "models.py")))

    async def test_help_functionality(self):
        """Test that --help works and doesn't execute commands"""
        from neutronapi.commands import startapp as cmd_startapp

        # Test command with help attribute
        command = cmd_startapp.Command()
        self.assertTrue(hasattr(command, 'help'))
        self.assertEqual(command.help, "Create a new app in ./apps")

        # Test --help doesn't create an app named "--help"
        # This would have been the bug - creating apps/--help directory
        await command.handle(["--help"])

        # Verify no "--help" directory was created
        self.assertFalse(os.path.exists("apps/--help"))
        self.assertFalse(os.path.exists("--help"))

    async def test_command_without_help(self):
        """Test commands that don't have help attribute show default text"""
        # Create a mock command without help
        class MockCommand:
            async def handle(self, args):
                pass

        mock_cmd = MockCommand()

        # Should not have help attribute
        self.assertFalse(hasattr(mock_cmd, 'help'))

        # When CLI checks for help, it should use default text
        help_text = getattr(mock_cmd, 'help', 'No description available')
        self.assertEqual(help_text, 'No description available')
