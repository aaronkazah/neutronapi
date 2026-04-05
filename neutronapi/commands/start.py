"""Start command using uvicorn with all options support."""
import argparse
import asyncio
import os
import sys
from typing import List

from neutronapi.commands.base import BaseCommand
from neutronapi.exceptions import CommandError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="start",
        description="Start the NeutronAPI ASGI server.",
        add_help=True,
    )
    parser.add_argument("bind", nargs="?", default=None, help="Optional [host:]port")
    parser.add_argument("--host", default=None, help="Bind host (default: 127.0.0.1 dev, 0.0.0.0 production)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default: 8000)")
    parser.add_argument("--production", action="store_true", help="Production mode (multi-worker, no reload)")
    parser.add_argument("--workers", type=int, default=None, help="Number of worker processes")

    reload_group = parser.add_mutually_exclusive_group()
    reload_group.add_argument("--reload", action="store_true", default=None, help="Enable auto-reload")
    reload_group.add_argument("--no-reload", action="store_true", help="Disable auto-reload")

    parser.add_argument("--reload-dir", action="append", default=None, help="Extra directory to watch")
    parser.add_argument("--reload-include", action="append", default=None, help="Include pattern for reload")
    parser.add_argument("--reload-exclude", action="append", default=None, help="Exclude pattern from reload")
    parser.add_argument("--log-level", choices=["debug", "info", "warning", "error", "critical"], default=None)

    access_group = parser.add_mutually_exclusive_group()
    access_group.add_argument("--access-log", action="store_true", default=None, help="Enable access log")
    access_group.add_argument("--no-access-log", action="store_true", help="Disable access log")

    parser.add_argument("--loop", default=None, help="Event loop implementation")
    parser.add_argument("--http", default=None, help="HTTP protocol implementation")
    parser.add_argument("--ws", default=None, help="WebSocket protocol implementation")
    parser.add_argument("--lifespan", default=None, help="Lifespan implementation")
    parser.add_argument("--ssl-keyfile", default=None, help="SSL key file")
    parser.add_argument("--ssl-certfile", default=None, help="SSL certificate file")
    return parser


class Command(BaseCommand):
    def __init__(self):
        super().__init__()
        self.help = "Start the ASGI server with auto-reload and production options."

    async def handle(self, args: List[str]) -> None:
        parser = _build_parser()
        opts = parser.parse_args(args)

        # Preflight: warn about unapplied migrations
        await self._preflight_migration_check()

        try:
            import uvicorn
        except ImportError:
            raise CommandError("uvicorn is required. Install with: pip install uvicorn")

        from neutronapi.conf import settings
        try:
            entry_point = settings.ENTRY
        except AttributeError as e:
            raise CommandError(
                "Could not load settings. Make sure apps/settings.py defines ENTRY. "
                f"Original error: {e}"
            )

        # Resolve bind positional (host:port or port)
        if opts.bind is not None:
            if ":" in opts.bind:
                host_part, port_part = opts.bind.split(":", 1)
                if opts.host is None:
                    opts.host = host_part
                if opts.port is None:
                    try:
                        opts.port = int(port_part)
                    except ValueError:
                        raise CommandError(f"Invalid port in '{opts.bind}'")
            else:
                try:
                    if opts.port is None:
                        opts.port = int(opts.bind)
                except ValueError:
                    raise CommandError(f"Invalid address '{opts.bind}'")

        # Build uvicorn kwargs from mode defaults + explicit overrides
        if opts.production:
            import multiprocessing
            cpu_count = multiprocessing.cpu_count()
            uvicorn_kwargs = {
                "host": opts.host or "0.0.0.0",
                "port": opts.port or 8000,
                "reload": False,
                "workers": opts.workers or (cpu_count * 2 + 1),
                "access_log": True,
                "log_level": opts.log_level or "warning",
            }
            self.stdout(f"Starting production server with {uvicorn_kwargs['workers']} workers...")
        else:
            # Dev mode — hand off to watchdog unless --no-reload
            if not opts.no_reload and opts.reload is not False:
                return await self._start_with_watchdog_reload(opts, entry_point)

            uvicorn_kwargs = {
                "host": opts.host or "127.0.0.1",
                "port": opts.port or 8000,
                "reload": False,
                "access_log": True,
                "log_level": opts.log_level or "info",
            }
            self.stdout("Starting development server without auto-reload...")

        # Apply explicit overrides
        if opts.workers is not None:
            uvicorn_kwargs["workers"] = opts.workers
            uvicorn_kwargs["reload"] = False
        if opts.reload is True:
            uvicorn_kwargs["reload"] = True
        if opts.no_access_log:
            uvicorn_kwargs["access_log"] = False
        elif opts.access_log is True:
            uvicorn_kwargs["access_log"] = True
        for key in ("reload_dir", "reload_include", "reload_exclude"):
            val = getattr(opts, key, None)
            if val:
                uvicorn_kwargs[key + "s"] = val
        for key in ("loop", "http", "ws", "lifespan", "ssl_keyfile", "ssl_certfile"):
            val = getattr(opts, key, None)
            if val is not None:
                uvicorn_kwargs[key] = val

        # Determine app reference
        if uvicorn_kwargs.get("reload") or uvicorn_kwargs.get("workers", 1) > 1:
            app_ref = entry_point
        else:
            try:
                from neutronapi.conf import get_app_from_entry
                app_ref = get_app_from_entry(entry_point)
            except (ImportError, AttributeError, ValueError) as e:
                raise CommandError(f"Could not load ASGI application from '{entry_point}': {e}")

        mode = "production" if opts.production else "development"
        self.stdout(f"Starting {mode} server at http://{uvicorn_kwargs['host']}:{uvicorn_kwargs['port']}/")
        self.stdout("Quit the server with CONTROL-C.")

        try:
            from uvicorn import Config, Server
            config = Config(app_ref, **uvicorn_kwargs)
            server = Server(config)
            await server.serve()
        except KeyboardInterrupt:
            self.stdout("\nServer stopped.")
        except Exception as e:
            raise CommandError(f"Error starting server: {e}")

    async def _preflight_migration_check(self) -> None:
        """Warn about unapplied migrations without blocking startup."""
        try:
            from neutronapi.db.migration_tracker import MigrationTracker
            from neutronapi.db.connection import get_databases
            from neutronapi.db import setup_databases
            from neutronapi.conf import settings

            base_dir = os.path.join(os.getcwd(), "apps")
            if not os.path.isdir(base_dir):
                return

            try:
                setup_databases(settings.DATABASES)
            except Exception:
                return

            async def _check():
                tracker = MigrationTracker(base_dir="apps")
                connection = await get_databases().get_connection("default")
                unapplied = await tracker.get_unapplied_migrations(connection)
                if unapplied:
                    self.stdout("\nWarning: You have unapplied migrations.")
                    self.stdout("Run 'python manage.py migrate' to apply them.\n")

            await asyncio.wait_for(_check(), timeout=3.0)
        except Exception:
            pass

    async def _start_with_watchdog_reload(self, opts, entry_point: str) -> None:
        """Start server with watchdog-based reload."""
        import time
        from pathlib import Path

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            return await self._start_uvicorn_with_reload(opts, entry_point)

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
            python = sys.executable
            os.execl(python, python, *sys.argv)

        clear_restart()

        host = opts.host or "127.0.0.1"
        port = opts.port or 8000
        log_level = opts.log_level or "info"
        reload_dirs = opts.reload_dir or [".", "apps", "neutronapi"]

        self.stdout("Starting development server with watchdog auto-reload...")
        self.stdout(f"Watching directories: {', '.join(reload_dirs)}")
        self.stdout(f"Starting server at http://{host}:{port}/")
        self.stdout("Auto-reload enabled. Quit with CONTROL-C.")

        command = self

        class FileChangeHandler(FileSystemEventHandler):
            def __init__(self):
                self.last_restart = 0.0
                self._restart_delay = 1

            def on_any_event(self, event):
                if event.is_directory or not event.src_path.endswith(".py"):
                    return
                current_time = time.time()
                if current_time - self.last_restart < self._restart_delay:
                    return
                self.last_restart = current_time
                command.stdout(f"\nDetected change in {event.src_path}")
                request_restart()

        observer = Observer()
        handler = FileChangeHandler()
        for directory in reload_dirs:
            if os.path.isdir(directory):
                observer.schedule(handler, directory, recursive=True)
        observer.start()

        try:
            from uvicorn import Config, Server

            config = Config(
                entry_point,
                host=host,
                port=port,
                log_level=log_level,
                reload=False,
                access_log=True,
            )
            server = Server(config)
            server_task = asyncio.create_task(server.serve())

            while True:
                if needs_restart():
                    clear_restart()
                    self.stdout("\nRestarting server...")
                    restart_server()
                if server_task.done():
                    break
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            self.stdout("\nShutting down...")
        except Exception as e:
            self.stderr(f"Error: {e}")
        finally:
            observer.stop()
            observer.join()

    async def _start_uvicorn_with_reload(self, opts, entry_point: str) -> None:
        """Fallback to uvicorn's built-in reload."""
        host = opts.host or "127.0.0.1"
        port = opts.port or 8000
        log_level = opts.log_level or "info"

        try:
            from uvicorn import Config, Server

            config = Config(
                entry_point,
                host=host,
                port=port,
                log_level=log_level,
                reload=True,
                access_log=True,
            )
            server = Server(config)
            await server.serve()
        except KeyboardInterrupt:
            self.stdout("\nServer stopped.")
        except Exception as e:
            raise CommandError(f"Error starting server: {e}")
