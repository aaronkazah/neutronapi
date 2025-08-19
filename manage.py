#!/usr/bin/env python
"""
Delegates to neutronapi.cli for command discovery and execution.
Keeps project validation inside commands or the central CLI, not here.
"""
import sys


def main() -> None:
    from neutronapi.cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
