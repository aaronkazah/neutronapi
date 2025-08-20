#!/usr/bin/env python3
"""
Minimal manage.py that forwards to neutronapi CLI main.
"""
import os
import sys


def main():
    # Set default settings module like Django does
    os.environ.setdefault('NEUTRONAPI_SETTINGS_MODULE', 'apps.settings')
    
    from neutronapi.cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()

