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
