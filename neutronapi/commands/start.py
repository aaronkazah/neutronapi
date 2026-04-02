"""
Start command using uvicorn with all options support.
"""
import os
import sys
from typing import List

from neutronapi.exceptions import CommandError


class Command:
    def __init__(self):
        self.help = """Start the ASGI server with auto-reload and production options.

Examples:
  python manage.py start                     # Dev mode with auto-reload
  python manage.py start --production        # Production mode (multi-worker, no reload)
  python manage.py start --port 8080         # Custom port
  python manage.py start --host 0.0.0.0      # Allow external connections
  python manage.py start --no-reload         # Disable auto-reload in dev mode

In development mode (default):
  - Auto-reload on file changes (*.py files)
  - Single worker process
  - Localhost only (127.0.0.1)
  - Verbose logging

In production mode (--production):
  - No auto-reload
  - Multiple workers (CPU cores * 2 + 1)
  - External connections allowed (0.0.0.0)
  - Minimal logging

For all options: python manage.py start --help"""

    async def handle(self, args: List[str]) -> None:
        """
        Start ASGI server with uvicorn.

        Usage:
            python manage.py start                        # Development mode with reload
            python manage.py start --production           # Production mode (auto workers, optimized)
            python manage.py start --production --workers 8  # Production with custom workers
            python manage.py start --host 0.0.0.0         # Custom host
            python manage.py start --port 8080            # Custom port

        Production mode automatically sets:
        - Multiple workers (CPU count * 2 + 1)
        - Host 0.0.0.0 (accept external connections)
        - Optimized event loop and HTTP parser
        - Warning-level logging
        - No auto-reload

        All options can be overridden. Supports all uvicorn options.
        """
        # Fast-path help: avoid any async DB checks or external calls
        if any(a in ("--help", "-h", "help") for a in args):
            print(self.help)
            print("\nAdvanced uvicorn options:")
            print("  --workers N          Number of worker processes")
            print("  --reload-dir DIR     Additional directory to watch")
            print("  --reload-include P   Include pattern for reload")
            print("  --reload-exclude P   Exclude pattern from reload")
            print("  --log-level LEVEL    Set log level (debug/info/warning/error)")
            print("  --ssl-keyfile FILE   SSL key file")
            print("  --ssl-certfile FILE  SSL certificate file")
            print("\nFor all uvicorn options: uvicorn --help")
            return
        # Preflight: warn about unapplied migrations (like Django)
        try:
            import asyncio
            import signal
            from neutronapi.db.migration_tracker import MigrationTracker
            from neutronapi.db.connection import get_databases

            async def _check_unapplied():
                base_dir = os.path.join(os.getcwd(), 'apps')
                if not os.path.isdir(base_dir):
                    return
                
                # Setup databases with settings configuration (same as migrate command)
                try:
                    from neutronapi.conf import settings
                    from neutronapi.db import setup_databases
                    setup_databases(settings.DATABASES)
                except Exception:
                    # If settings import fails, use default configuration
                    pass
                
                tracker = MigrationTracker(base_dir='apps')
                connection = await get_databases().get_connection('default')
                unapplied = await tracker.get_unapplied_migrations(connection)
                if unapplied:
                    print("\nWarning: You have unapplied migrations.")
                    print("Run 'python manage.py migrate' to apply them before starting the server.\n")

            # Run check with timeout to prevent hanging
            try:
                await asyncio.wait_for(_check_unapplied(), timeout=3.0)
            except asyncio.TimeoutError:
                pass
        except Exception:
            # Never block startup for migration warnings
            pass

        try:
            import uvicorn
        except ImportError:
            raise CommandError("uvicorn is required to run the server. Install it with: pip install uvicorn")

        # Get the entry point string from settings
        try:
            from neutronapi.conf import settings
            entry_point = settings.ENTRY
        except (ImportError, AttributeError) as e:
            raise CommandError(
                "Could not load settings. Make sure apps/settings.py exists and defines "
                "ENTRY (for example 'apps.entry:app'). "
                f"Original error: {e}"
            )

        # Check for production mode
        production_mode = False
        if "--production" in args:
            production_mode = True
            args = [arg for arg in args if arg != "--production"]  # Remove --production flag

        # Default settings
        if production_mode:
            # Production defaults - optimized for deployment
            import multiprocessing
            cpu_count = multiprocessing.cpu_count()
            workers = cpu_count * 2 + 1  # Common formula for async apps

            defaults = {
                "host": "0.0.0.0",
                "port": 8000,
                "reload": False,
                "workers": workers,
                "access_log": True,
                "log_level": "warning",  # Less verbose in production
                # Don't force specific loop/http - let uvicorn decide based on availability
            }
            print(f"Starting production server with {workers} workers...")
        else:
            # Development mode - use watchdog-based reload instead of uvicorn's
            if "--no-reload" not in args:
                return await self._start_with_watchdog_reload(args, entry_point)

            defaults = {
                "host": "127.0.0.1",
                "port": 8000,
                "reload": False,
                "access_log": True,
                "log_level": "info",
            }
            print("Starting development server without auto-reload...")

        # Parse uvicorn-style arguments
        uvicorn_kwargs = defaults.copy()

        i = 0
        while i < len(args):
            arg = args[i]

            if arg == "--help":
                # Already handled at top; keep for completeness
                print(self.handle.__doc__)
                print("\nTip: install 'uvicorn' to see all runtime options (uvicorn --help).")
                return
            elif arg == "--host":
                if i + 1 < len(args):
                    uvicorn_kwargs["host"] = args[i + 1]
                    i += 1
                else:
                    raise CommandError("--host requires a value")
            elif arg == "--port":
                if i + 1 < len(args):
                    try:
                        uvicorn_kwargs["port"] = int(args[i + 1])
                        i += 1
                    except ValueError:
                        raise CommandError(f"Invalid port '{args[i + 1]}'")
                else:
                    raise CommandError("--port requires a value")
            elif arg == "--reload":
                uvicorn_kwargs["reload"] = True
            elif arg == "--no-reload":
                uvicorn_kwargs["reload"] = False
            elif arg == "--reload-dir":
                if i + 1 < len(args):
                    if "reload_dirs" not in uvicorn_kwargs:
                        uvicorn_kwargs["reload_dirs"] = []
                    uvicorn_kwargs["reload_dirs"].append(args[i + 1])
                    i += 1
                else:
                    raise CommandError("--reload-dir requires a value")
            elif arg == "--reload-exclude":
                if i + 1 < len(args):
                    if "reload_excludes" not in uvicorn_kwargs:
                        uvicorn_kwargs["reload_excludes"] = []
                    uvicorn_kwargs["reload_excludes"].append(args[i + 1])
                    i += 1
                else:
                    raise CommandError("--reload-exclude requires a value")
            elif arg == "--reload-include":
                if i + 1 < len(args):
                    if "reload_includes" not in uvicorn_kwargs:
                        uvicorn_kwargs["reload_includes"] = []
                    uvicorn_kwargs["reload_includes"].append(args[i + 1])
                    i += 1
                else:
                    raise CommandError("--reload-include requires a value")
            elif arg == "--workers":
                if i + 1 < len(args):
                    try:
                        uvicorn_kwargs["workers"] = int(args[i + 1])
                        uvicorn_kwargs["reload"] = False  # Can't use reload with workers
                        i += 1
                    except ValueError:
                        raise CommandError(f"Invalid workers '{args[i + 1]}'")
                else:
                    raise CommandError("--workers requires a value")
            elif arg == "--log-level":
                if i + 1 < len(args):
                    uvicorn_kwargs["log_level"] = args[i + 1]
                    i += 1
                else:
                    raise CommandError("--log-level requires a value")
            elif arg == "--access-log":
                uvicorn_kwargs["access_log"] = True
            elif arg == "--no-access-log":
                uvicorn_kwargs["access_log"] = False
            elif arg == "--loop":
                if i + 1 < len(args):
                    uvicorn_kwargs["loop"] = args[i + 1]
                    i += 1
                else:
                    raise CommandError("--loop requires a value")
            elif arg == "--http":
                if i + 1 < len(args):
                    uvicorn_kwargs["http"] = args[i + 1]
                    i += 1
                else:
                    raise CommandError("--http requires a value")
            elif arg == "--ws":
                if i + 1 < len(args):
                    uvicorn_kwargs["ws"] = args[i + 1]
                    i += 1
                else:
                    raise CommandError("--ws requires a value")
            elif arg == "--lifespan":
                if i + 1 < len(args):
                    uvicorn_kwargs["lifespan"] = args[i + 1]
                    i += 1
                else:
                    raise CommandError("--lifespan requires a value")
            elif arg == "--ssl-keyfile":
                if i + 1 < len(args):
                    uvicorn_kwargs["ssl_keyfile"] = args[i + 1]
                    i += 1
                else:
                    raise CommandError("--ssl-keyfile requires a value")
            elif arg == "--ssl-certfile":
                if i + 1 < len(args):
                    uvicorn_kwargs["ssl_certfile"] = args[i + 1]
                    i += 1
                else:
                    raise CommandError("--ssl-certfile requires a value")
            elif arg.startswith("--"):
                print(f"Warning: Unrecognized option '{arg}', ignoring")
            else:
                # Assume it's host:port format
                if ":" in arg:
                    host, port_str = arg.split(":", 1)
                    uvicorn_kwargs["host"] = host
                    try:
                        uvicorn_kwargs["port"] = int(port_str)
                    except ValueError:
                        raise CommandError(f"Invalid port in '{arg}'")
                else:
                    try:
                        uvicorn_kwargs["port"] = int(arg)
                    except ValueError:
                        raise CommandError(f"Invalid address '{arg}'")

            i += 1

        # Determine app or import string based on reload mode or workers
        if uvicorn_kwargs.get("reload", True) or uvicorn_kwargs.get("workers", 1) > 1:
            # For reload mode or multiple workers, use the entry point string directly
            app_or_import_string = entry_point
        else:
            # For single worker non-reload mode, we can import the app object
            try:
                from neutronapi.conf import get_app_from_entry
                app_or_import_string = get_app_from_entry(entry_point)
            except (ImportError, AttributeError, ValueError) as e:
                raise CommandError(
                    "Could not load the ASGI application from ENTRY. "
                    f"Check '{entry_point}'. Original error: {e}"
                )

        # Show startup message
        mode = "production" if production_mode else "development"
        print(f"Starting {mode} server at http://{uvicorn_kwargs['host']}:{uvicorn_kwargs['port']}/")
        if uvicorn_kwargs.get("reload"):
            print("Auto-reload enabled. Quit with CONTROL-C.")
            # Show reload configuration in debug mode
            if uvicorn_kwargs.get("log_level") == "debug":
                print(f"Debug: Reload directories: {uvicorn_kwargs.get('reload_dirs', [])}")
                print(f"Debug: Reload includes: {uvicorn_kwargs.get('reload_includes', [])}")
                print(f"Debug: Reload excludes: {uvicorn_kwargs.get('reload_excludes', [])}")
        else:
            print("Quit the server with CONTROL-C.")

        # Run the server using async Server.serve
        try:
            from uvicorn import Config, Server

            # Debug logging for reload configuration
            if uvicorn_kwargs.get("reload") and uvicorn_kwargs.get("log_level") == "debug":
                print("\nReload configuration:")
                for key, value in uvicorn_kwargs.items():
                    if "reload" in key:
                        print(f"  {key}: {value}")

            config = Config(app_or_import_string, **uvicorn_kwargs)
            server = Server(config)
            await server.serve()
        except KeyboardInterrupt:
            print("\nServer stopped.")
        except Exception as e:
            if uvicorn_kwargs.get("log_level") == "debug":
                import traceback

                traceback.print_exc()
            raise CommandError(f"Error starting server: {e}")

    async def _start_with_watchdog_reload(self, args: List[str], entry_point: str) -> None:
        """Start server with watchdog-based reload using restart file approach."""
        import time
        import os
        import asyncio
        from pathlib import Path

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            # Fall back to uvicorn reload
            return await self._start_uvicorn_with_reload(args, entry_point)

        # Restart file approach
        BASE_DIR = Path(os.getcwd())
        RESTART_FILE = BASE_DIR / ".restart"

        def needs_restart() -> bool:
            return RESTART_FILE.exists()

        def request_restart():
            RESTART_FILE.touch()

        def clear_restart():
            if RESTART_FILE.exists():
                RESTART_FILE.unlink()

        def restart_server():
            """Restart the server process using os.execl."""
            python = sys.executable
            os.execl(python, python, *sys.argv)

        clear_restart()  # Clear any existing restart flag

        # Parse arguments
        host = "127.0.0.1"
        port = 8000
        log_level = "info"
        reload_dirs = [".", "apps", "neutronapi"]

        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--host" and i + 1 < len(args):
                host = args[i + 1]
                i += 1
            elif arg == "--port" and i + 1 < len(args):
                port = int(args[i + 1])
                i += 1
            elif arg == "--log-level" and i + 1 < len(args):
                log_level = args[i + 1]
                i += 1
            elif arg == "--reload-dir" and i + 1 < len(args):
                reload_dirs.append(args[i + 1])
                i += 1
            i += 1

        print("Starting development server with watchdog auto-reload...")
        print(f"Watching directories: {', '.join(reload_dirs)}")
        print(f"Starting server at http://{host}:{port}/")
        print("Auto-reload enabled. Quit with CONTROL-C.")

        # File change handler
        class FileChangeHandler(FileSystemEventHandler):
            def __init__(self):
                self.last_restart = 0
                self._restart_delay = 1

            def on_any_event(self, event):
                if event.is_directory or not event.src_path.endswith(".py"):
                    return

                current_time = time.time()
                if current_time - self.last_restart < self._restart_delay:
                    return

                self.last_restart = current_time
                print(f"\nDetected change in {event.src_path}")
                request_restart()

        # Set up watchdog
        observer = Observer()
        handler = FileChangeHandler()

        # Add watchers for each directory
        for directory in reload_dirs:
            if os.path.isdir(directory):
                observer.schedule(handler, directory, recursive=True)

        observer.start()

        try:
            # Start uvicorn server directly using asyncio
            import uvicorn
            from uvicorn import Config, Server

            config = Config(
                entry_point,
                host=host,
                port=port,
                log_level=log_level,
                reload=False,  # We handle reload via watchdog
                access_log=True
            )
            server = Server(config)

            # Create server task
            server_task = asyncio.create_task(server.serve())

            # Watch for restart requests
            while True:
                # Check for restart flag
                if needs_restart():
                    clear_restart()
                    print("\nRestarting server...")
                    restart_server()  # This will restart the entire process

                # Check if server task is done
                if server_task.done():
                    break

                await asyncio.sleep(1)

        except KeyboardInterrupt:
            print("\nShutting down...")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            observer.stop()
            observer.join()

    async def _start_uvicorn_with_reload(self, args: List[str], entry_point: str) -> None:
        """Fallback to uvicorn's built-in reload."""
        # Continue with the original uvicorn implementation
        import os
