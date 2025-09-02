import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch
import asyncio

import neutronapi.cli as cli


class TestCustomCommands(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmpdir = tempfile.mkdtemp(prefix="neutronapi_custom_cmds_")
        os.chdir(self.tmpdir)
        
        # Create a project structure with custom commands
        self._create_project_structure()

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_project_structure(self):
        """Create a minimal project structure with custom commands."""
        # Create apps directory
        os.makedirs("apps", exist_ok=True)
        
        # Create settings.py
        with open("apps/settings.py", "w") as f:
            f.write("""
# Minimal settings for testing
DATABASE_URL = "sqlite:///test.db"
DATABASES = {
    'default': {
        'ENGINE': 'sqlite',
        'NAME': 'test.db',
    }
}
""")
        
        # Create entry.py
        with open("apps/entry.py", "w") as f:
            f.write("""
# Minimal entry.py for testing
from neutronapi import NeutronAPI

app = NeutronAPI()
""")
        
        # Create a test app with custom commands
        os.makedirs("apps/blog/commands", exist_ok=True)
        
        # Create __init__.py files
        with open("apps/__init__.py", "w") as f:
            f.write("")
        with open("apps/blog/__init__.py", "w") as f:
            f.write("")
        with open("apps/blog/commands/__init__.py", "w") as f:
            f.write("")
        
        # Create a custom command using BaseCommand
        with open("apps/blog/commands/greet.py", "w") as f:
            f.write("""
from neutronapi.commands.base import BaseCommand

class Command(BaseCommand):
    help = "A custom greeting command"

    async def ahandle(self, *args, **options):
        name = args[0] if args else "World"
        self.success(f"Hello, {name}!")
        return 0
    
    # For backward compatibility, also provide handle method
    async def handle(self, args):
        return await self.ahandle(*args)
""")
        
        # Create another custom command with synchronous handle
        with open("apps/blog/commands/count.py", "w") as f:
            f.write("""
from neutronapi.commands.base import BaseCommand

class Command(BaseCommand):
    help = "Count up to a number"

    def handle(self, *args, **options):
        try:
            args_list = list(args) if args else []
            count = int(args_list[0]) if args_list else 5
            for i in range(1, count + 1):
                self.success(f"Count: {i}")
            return 0
        except ValueError:
            self.error("Please provide a valid number")
            return 1
""")
        
        # Create a command that demonstrates error handling
        with open("apps/blog/commands/error_demo.py", "w") as f:
            f.write("""
from neutronapi.commands.base import BaseCommand

class Command(BaseCommand):
    help = "Demonstrate error handling"

    async def ahandle(self, *args, **options):
        args_list = list(args) if args else []
        if args_list and args_list[0] == "error":
            raise RuntimeError("This is a demo error")
        self.success("No error occurred")
        return 0
    
    # For backward compatibility
    async def handle(self, args):
        return await self.ahandle(*args)
""")

    async def test_discover_custom_commands(self):
        """Test that custom commands are discovered from apps/*/commands directories."""
        commands = cli.discover_commands()
        
        # Check that our custom commands are discovered
        self.assertIn('greet', commands)
        self.assertIn('count', commands)
        self.assertIn('error_demo', commands)
        
        # Check that built-in commands are still there
        self.assertIn('makemigrations', commands)
        self.assertIn('migrate', commands)

    async def test_custom_async_command_execution(self):
        """Test executing a custom async command."""
        commands = cli.discover_commands()
        greet_command = commands['greet']
        
        # Capture stdout to verify the command output
        with patch('builtins.print') as mock_print:
            result = await greet_command.handle(['Alice'])
            mock_print.assert_called_with("Hello, Alice!")
        
        # Test with no args
        with patch('builtins.print') as mock_print:
            result = await greet_command.handle([])
            mock_print.assert_called_with("Hello, World!")

    async def test_custom_sync_command_execution(self):
        """Test executing a custom synchronous command."""
        commands = cli.discover_commands()
        count_command = commands['count']
        
        # Test counting to 3
        with patch('builtins.print') as mock_print:
            result = count_command.handle('3')  # Pass as args to handle
            expected_calls = [
                unittest.mock.call("Count: 1"),
                unittest.mock.call("Count: 2"),
                unittest.mock.call("Count: 3")
            ]
            mock_print.assert_has_calls(expected_calls)
            self.assertEqual(result, 0)
        
        # Test invalid input
        with patch('builtins.print') as mock_print:
            result = count_command.handle('invalid')
            mock_print.assert_called_with("Error: Please provide a valid number")
            self.assertEqual(result, 1)

    async def test_custom_command_error_handling(self):
        """Test that custom command errors are handled properly."""
        commands = cli.discover_commands()
        error_command = commands['error_demo']
        
        # Test normal execution
        with patch('builtins.print') as mock_print:
            result = await error_command.handle([])
            mock_print.assert_called_with("No error occurred")
            self.assertEqual(result, 0)
        
        # Test error case
        with self.assertRaises(RuntimeError) as context:
            await error_command.handle(['error'])
        self.assertEqual(str(context.exception), "This is a demo error")

    def test_command_help_attribute(self):
        """Test that custom commands have help attributes."""
        commands = cli.discover_commands()
        
        self.assertEqual(commands['greet'].help, "A custom greeting command")
        self.assertEqual(commands['count'].help, "Count up to a number")
        self.assertEqual(commands['error_demo'].help, "Demonstrate error handling")

    async def test_invalid_command_module_ignored(self):
        """Test that invalid command modules are ignored during discovery."""
        # Create a command file with syntax error
        with open("apps/blog/commands/broken.py", "w") as f:
            f.write("invalid python syntax !!!")
        
        # Create a command file without Command class
        with open("apps/blog/commands/no_command.py", "w") as f:
            f.write("""
def some_function():
    pass
""")
        
        # Discovery should not fail and should ignore broken commands
        commands = cli.discover_commands()
        
        # Broken commands should not be in the discovered commands
        self.assertNotIn('broken', commands)
        self.assertNotIn('no_command', commands)
        
        # Valid commands should still be there
        self.assertIn('greet', commands)
        self.assertIn('count', commands)

    def test_multiple_apps_with_commands(self):
        """Test discovery of commands from multiple apps."""
        # Create another app with commands
        os.makedirs("apps/users/commands", exist_ok=True)
        
        with open("apps/users/__init__.py", "w") as f:
            f.write("")
        with open("apps/users/commands/__init__.py", "w") as f:
            f.write("")
        
        # Create a user management command
        with open("apps/users/commands/create_user.py", "w") as f:
            f.write("""
from neutronapi.commands.base import BaseCommand

class Command(BaseCommand):
    help = "Create a new user"

    async def ahandle(self, *args, **options):
        args_list = list(args) if args else []
        username = args_list[0] if args_list else "defaultuser"
        self.success(f"Created user: {username}")
        return 0
    
    # For backward compatibility
    async def handle(self, args):
        return await self.ahandle(*args)
""")
        
        commands = cli.discover_commands()
        
        # Commands from both apps should be discovered
        self.assertIn('greet', commands)  # from blog app
        self.assertIn('create_user', commands)  # from users app
        
        # Built-in commands should still be there
        self.assertIn('makemigrations', commands)


if __name__ == '__main__':
    unittest.main()