"""
Base command class for NeutronAPI CLI commands.

Provides a consistent interface similar to Django's BaseCommand.
"""
from __future__ import annotations

import asyncio
import sys
from typing import List, Optional, Any


class BaseCommand:
    """
    Base class for all NeutronAPI commands.

    Provides common functionality and a consistent interface for command execution.
    """

    help = "A NeutronAPI command."

    def __init__(self):
        """Initialize the command."""
        self.quiet = False
    
    def add_arguments(self, parser) -> None:
        """
        Override this method to add command-specific arguments.
        This method is called when setting up argument parsing.
        
        Args:
            parser: The argument parser to add arguments to
        """
        pass
    
    def handle(self, *args, **options) -> Optional[int]:
        """
        The actual logic of the command. Subclasses must implement this method.
        
        Args:
            args: Positional arguments passed to the command
            options: Keyword arguments/options passed to the command
            
        Returns:
            Optional exit code (0 for success, non-zero for failure)
        """
        raise NotImplementedError("Subclasses must implement the handle() method")
    
    async def ahandle(self, *args, **options) -> Optional[int]:
        """
        Async version of handle(). Override this for async commands.
        
        Args:
            args: Positional arguments passed to the command
            options: Keyword arguments/options passed to the command
            
        Returns:
            Optional exit code (0 for success, non-zero for failure)
        """
        # Default implementation runs the sync handle in an executor
        if asyncio.iscoroutinefunction(self.handle):
            return await self.handle(*args, **options)
        else:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.handle, *args, **options)
    
    def stdout(self, message: str = "") -> None:
        """Print a message to stdout, respecting the quiet flag."""
        if not self.quiet:
            print(message)

    def stderr(self, message: str) -> None:
        """Print a message to stderr (always printed, ignores quiet flag)."""
        print(message, file=sys.stderr)

    def print_help(self) -> None:
        """Print help information for this command."""
        self.stdout(f"{self.help}")
        if self.handle.__doc__:
            self.stdout(f"\n{self.handle.__doc__}")

    def success(self, message: str) -> None:
        """Print a success message."""
        self.stdout(message)

    def warning(self, message: str) -> None:
        """Print a warning message."""
        self.stdout(f"Warning: {message}")

    def error(self, message: str) -> None:
        """Print an error message."""
        self.stderr(f"Error: {message}")


class Command(BaseCommand):
    """
    Alias for BaseCommand to maintain backward compatibility.
    
    This allows existing commands to continue working while providing
    the BaseCommand class for new commands.
    """
    pass