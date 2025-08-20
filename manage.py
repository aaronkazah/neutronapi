#!/usr/bin/env python3
"""
Minimal manage.py that forwards to neutronapi CLI main.
"""
import sys


def main():
    from neutronapi.cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()

