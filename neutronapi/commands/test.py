"""Test command with explicit database selection and Django-like options."""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import os
import re
import shutil
import socket
import sys
import tempfile
import unittest
from copy import deepcopy
from io import StringIO
from typing import Iterable, List, Optional, Tuple


class Command:
    """Run tests with explicit provider selection and discovery filtering."""

    def __init__(self) -> None:
        self._pg_container: Optional[str] = None
        self._pg_data_dir: Optional[str] = None
        self._keepdb = False
        self._selected_database = "sqlite"
        self._active_database_config: dict = {}
        self.help = self._build_parser().format_help()

    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="python manage.py test",
            description="Run tests with Django-like functionality.",
            add_help=False,
            formatter_class=argparse.RawTextHelpFormatter,
        )
        parser.add_argument("targets", nargs="*", help="Optional test labels, modules, or apps")
        parser.add_argument("-h", "--help", action="store_true", dest="help_requested")
        parser.add_argument("-v", "--verbosity", type=int, choices=[0, 1, 2, 3], default=1)
        parser.add_argument("-q", "--quiet", action="store_true")
        parser.add_argument("--failfast", action="store_true")
        parser.add_argument("--parallel", nargs="?", const="auto")
        parser.add_argument("--reverse", action="store_true")
        parser.add_argument("-k", dest="pattern")
        parser.add_argument("--tag", action="append", default=[])
        parser.add_argument("--exclude-tag", action="append", default=[])
        parser.add_argument("--cov", "--coverage", action="store_true", dest="coverage")
        parser.add_argument("--keepdb", action="store_true")
        parser.add_argument("--debug-sql", action="store_true")
        parser.add_argument(
            "--database",
            choices=["auto", "sqlite", "postgres"],
            default="auto",
            help="Database provider to run tests against.",
        )
        return parser

    async def safe_shutdown(self) -> None:
        """Safely shutdown database connections with timeout."""
        try:
            from neutronapi.db import shutdown_all_connections

            await asyncio.wait_for(shutdown_all_connections(), timeout=5)
        except (ImportError, asyncio.TimeoutError, Exception):
            return

    async def run_forced_shutdown(self) -> None:
        """Run shutdown in the current event loop context."""
        await self.safe_shutdown()

    def _normalize_engine(self, value: str) -> str:
        engine = (value or "").lower().strip()
        if engine in {
            "django.db.backends.sqlite3",
            "sqlite3",
            "sqlite",
            "aiosqlite",
        }:
            return "sqlite"
        if engine in {
            "django.db.backends.postgresql",
            "django.db.backends.postgresql_psycopg2",
            "postgres",
            "postgresql",
            "psycopg2",
            "asyncpg",
        }:
            return "postgres"
        return "sqlite"

    def _default_postgres_config(self) -> dict:
        return {
            "ENGINE": "asyncpg",
            "HOST": os.getenv("PGHOST", "127.0.0.1"),
            "PORT": int(os.getenv("PGPORT", "5432")),
            "NAME": os.getenv("PGDATABASE", "neutronapi"),
            "USER": os.getenv("PGUSER", "postgres"),
            "PASSWORD": os.getenv("PGPASSWORD", "postgres"),
        }

    def _set_databases(self, databases: dict) -> None:
        from neutronapi.conf import settings

        loaded = settings._setup()
        loaded._settings["DATABASES"] = deepcopy(databases)

    def _set_default_database(self, db_config: dict) -> None:
        from neutronapi.conf import settings

        loaded = settings._setup()
        databases = deepcopy(loaded._settings.get("DATABASES", {}))
        databases["default"] = deepcopy(db_config)
        self._set_databases(databases)

    def _postgres_test_database_name(self, name: str) -> str:
        base = (name or "neutronapi").strip() or "neutronapi"
        if base.startswith("test_"):
            return base
        return f"test_{base}"

    def _apply_postgres_runtime_env(self, db_config: dict) -> None:
        os.environ["NEUTRONAPI_TEST_DATABASE"] = "postgres"
        os.environ["PGHOST"] = str(db_config.get("HOST", "127.0.0.1"))
        os.environ["PGPORT"] = str(db_config.get("PORT", 5432))
        os.environ["PGDATABASE"] = str(db_config.get("NAME", "test_neutronapi"))
        os.environ["PGUSER"] = str(db_config.get("USER", "postgres"))
        os.environ["PGPASSWORD"] = str(db_config.get("PASSWORD", "postgres"))

    def _mark_managed_postgres_owner(self, db_config: dict) -> None:
        os.environ["NEUTRONAPI_TEST_PG_OWNER"] = str(os.getpid())
        self._apply_postgres_runtime_env(db_config)

    def _managed_postgres_owner(self) -> Optional[str]:
        return os.getenv("NEUTRONAPI_TEST_PG_OWNER")

    def _using_inherited_managed_postgres(self) -> bool:
        owner = self._managed_postgres_owner()
        return bool(owner and owner != str(os.getpid()))

    def _reserve_postgres_port(self, preferred: int) -> int:
        for candidate in (preferred, 0):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind(("127.0.0.1", candidate))
                except OSError:
                    continue
                return int(sock.getsockname()[1])
        raise RuntimeError("Could not reserve a local TCP port for PostgreSQL")

    async def _has_existing_postgres_server(self, db_config: dict) -> bool:
        """Check if PostgreSQL server is already running and accessible."""
        try:
            import asyncpg

            conn = await asyncpg.connect(
                host=db_config.get("HOST", "localhost"),
                port=db_config.get("PORT", 5432),
                database="postgres",
                user=db_config.get("USER", "postgres"),
                password=db_config.get("PASSWORD", ""),
            )
            await conn.close()
            return True
        except Exception:
            return False

    async def _setup_test_database(self, db_config: dict) -> None:
        """Create a test database on an existing PostgreSQL server."""
        import asyncpg

        test_db_name = self._postgres_test_database_name(db_config.get("NAME", "neutronapi"))
        updated = dict(db_config)
        updated["NAME"] = test_db_name
        self._set_default_database(updated)
        self._active_database_config = updated

        conn = await asyncpg.connect(
            host=updated.get("HOST", "localhost"),
            port=updated.get("PORT", 5432),
            database="postgres",
            user=updated.get("USER", "postgres"),
            password=updated.get("PASSWORD", ""),
        )
        try:
            if not self._keepdb:
                dangling_dbs = await conn.fetch(
                    "SELECT datname FROM pg_database WHERE datname LIKE 'test_%'"
                )
                for db_row in dangling_dbs:
                    db_name = db_row["datname"]
                    await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')

            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1",
                test_db_name,
            )
            if not exists:
                await conn.execute(f'CREATE DATABASE "{test_db_name}"')
        finally:
            await conn.close()

    async def _run_async(self, *cmd: str, timeout: Optional[float] = None) -> Tuple[int, str, str]:
        """Run a subprocess asynchronously and capture output."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise
        return proc.returncode, stdout.decode(), stderr.decode()

    async def _bootstrap_postgres(self) -> bool:
        """Start a disposable PostgreSQL container in Docker if available."""
        self._pg_container = None
        self._pg_data_dir = None
        docker = shutil.which("docker")
        if not docker:
            return False

        host = "127.0.0.1"
        preferred_port = int(os.getenv("PGPORT", "54329"))
        port = self._reserve_postgres_port(preferred_port)
        dbname = self._postgres_test_database_name(os.getenv("PGDATABASE", "neutronapi"))
        user = os.getenv("PGUSER", "postgres")
        password = os.getenv("PGPASSWORD", "postgres")

        try:
            code, _, _ = await self._run_async(docker, "info", timeout=5)
            if code != 0:
                return False

            image = "postgres:15-alpine"
            code, _, _ = await self._run_async(docker, "image", "inspect", image, timeout=5)
            if code != 0:
                code, _, _ = await self._run_async(docker, "pull", image, timeout=300)
                if code != 0:
                    return False

            name = f"neutronapi_test_pg_{os.getpid()}"
            await self._run_async(docker, "rm", "-f", name, timeout=10)
            code, out, _ = await self._run_async(docker, "ps", "-q", "-f", f"name={name}", timeout=5)
            if not out.strip():
                code, _, _ = await self._run_async(
                    docker,
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    name,
                    "-e",
                    f"POSTGRES_PASSWORD={password}",
                    "-e",
                    f"POSTGRES_DB={dbname}",
                    "-e",
                    f"POSTGRES_USER={user}",
                    "-p",
                    f"{port}:5432",
                    image,
                    timeout=60,
                )
                if code != 0:
                    return False
            self._pg_container = name
        except (asyncio.TimeoutError, Exception):
            return False

        try:
            import asyncpg

            for _ in range(60):
                try:
                    conn = await asyncpg.connect(
                        host=host,
                        port=port,
                        database=dbname,
                        user=user,
                        password=password,
                    )
                    await conn.close()
                    updated = {
                        "ENGINE": "asyncpg",
                        "HOST": host,
                        "PORT": port,
                        "NAME": dbname,
                        "USER": user,
                        "PASSWORD": password,
                    }
                    self._set_default_database(updated)
                    self._active_database_config = updated
                    self._mark_managed_postgres_owner(updated)
                    return True
                except Exception:
                    await asyncio.sleep(0.25)
        except Exception:
            return False

        return False

    async def _bootstrap_postgres_native(self) -> bool:
        """Start a disposable local PostgreSQL instance when Docker is unavailable or unsuitable."""
        self._pg_container = None
        self._pg_data_dir = None

        initdb = shutil.which("initdb") or ("/opt/homebrew/bin/initdb" if os.path.exists("/opt/homebrew/bin/initdb") else None)
        pg_ctl = shutil.which("pg_ctl") or ("/opt/homebrew/bin/pg_ctl" if os.path.exists("/opt/homebrew/bin/pg_ctl") else None)
        if not initdb or not pg_ctl:
            return False

        host = "127.0.0.1"
        preferred_port = int(os.getenv("PGPORT", "54329"))
        port = self._reserve_postgres_port(preferred_port)
        dbname = self._postgres_test_database_name(os.getenv("PGDATABASE", "neutronapi"))
        user = os.getenv("PGUSER", "postgres")
        password = os.getenv("PGPASSWORD", "postgres")
        data_dir = tempfile.mkdtemp(prefix="neutronapi-pg-")
        log_path = os.path.join(data_dir, "postgres.log")

        try:
            code, _, _ = await self._run_async(initdb, "-A", "trust", "-U", user, data_dir, timeout=60)
            if code != 0:
                shutil.rmtree(data_dir, ignore_errors=True)
                return False

            code, _, _ = await self._run_async(
                pg_ctl,
                "-D",
                data_dir,
                "-l",
                log_path,
                "-o",
                f"-F -p {port} -h {host}",
                "-w",
                "start",
                timeout=60,
            )
            if code != 0:
                shutil.rmtree(data_dir, ignore_errors=True)
                return False

            import asyncpg

            conn = await asyncpg.connect(
                host=host,
                port=port,
                database="postgres",
                user=user,
                password=password,
            )
            try:
                exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", dbname)
                if not exists:
                    await conn.execute(f'CREATE DATABASE "{dbname}"')
            finally:
                await conn.close()

            updated = {
                "ENGINE": "asyncpg",
                "HOST": host,
                "PORT": port,
                "NAME": dbname,
                "USER": user,
                "PASSWORD": password,
            }
            self._pg_data_dir = data_dir
            self._set_default_database(updated)
            self._active_database_config = updated
            self._mark_managed_postgres_owner(updated)
            return True
        except Exception:
            if self._pg_data_dir:
                try:
                    await self._run_async(pg_ctl, "-D", data_dir, "-m", "fast", "stop", timeout=20)
                except Exception:
                    pass
            shutil.rmtree(data_dir, ignore_errors=True)
            self._pg_data_dir = None
            return False

    async def _teardown_postgres(self) -> None:
        """Stop the disposable PostgreSQL container if we started it."""
        if self._keepdb:
            return

        try:
            if self._pg_container:
                docker = shutil.which("docker")
                if docker:
                    await self._run_async(docker, "stop", self._pg_container, timeout=10)
            if self._pg_data_dir:
                pg_ctl = shutil.which("pg_ctl") or ("/opt/homebrew/bin/pg_ctl" if os.path.exists("/opt/homebrew/bin/pg_ctl") else None)
                if pg_ctl:
                    await self._run_async(pg_ctl, "-D", self._pg_data_dir, "-m", "fast", "stop", timeout=20)
        except Exception:
            pass
        finally:
            if self._pg_data_dir:
                shutil.rmtree(self._pg_data_dir, ignore_errors=True)
                self._pg_data_dir = None
            self._pg_container = None
            if self._managed_postgres_owner() == str(os.getpid()):
                os.environ.pop("NEUTRONAPI_TEST_PG_OWNER", None)

    async def _cleanup_test_database(self) -> None:
        """Drop the temporary PostgreSQL database when appropriate."""
        if (
            self._keepdb
            or self._selected_database != "postgres"
            or self._pg_container
            or self._pg_data_dir
            or self._using_inherited_managed_postgres()
        ):
            return

        db_config = self._active_database_config
        db_name = db_config.get("NAME", "")
        if not db_name.startswith("test_"):
            return

        try:
            import asyncpg

            conn = await asyncpg.connect(
                host=db_config.get("HOST", "localhost"),
                port=db_config.get("PORT", 5432),
                database="postgres",
                user=db_config.get("USER", "postgres"),
                password=db_config.get("PASSWORD", ""),
            )
            try:
                await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            finally:
                await conn.close()
        except Exception:
            pass

    async def _configure_database_mode(self, requested_mode: str, verbosity: int) -> str:
        from neutronapi.conf import is_neutronapi_development, settings
        from neutronapi.db.connection import setup_databases

        os.environ.pop("NEUTRONAPI_TEST_DATABASE", None)
        settings.reset()

        in_framework_repo = is_neutronapi_development()
        if requested_mode == "auto":
            if in_framework_repo:
                resolved_mode = "sqlite"
                os.environ["NEUTRONAPI_TEST_DATABASE"] = resolved_mode
                settings.reset()
            else:
                resolved_mode = self._normalize_engine(settings.DATABASES["default"].get("ENGINE", ""))
        else:
            resolved_mode = requested_mode
            if in_framework_repo:
                os.environ["NEUTRONAPI_TEST_DATABASE"] = resolved_mode
                settings.reset()

        loaded = settings._setup()
        current_db = deepcopy(loaded._settings.get("DATABASES", {}).get("default", {}))

        if resolved_mode == "sqlite":
            sqlite_db = {"ENGINE": "aiosqlite", "NAME": ":memory:"}
            self._set_default_database(sqlite_db)
            self._active_database_config = sqlite_db
            setup_databases(settings.DATABASES)
            self._selected_database = "sqlite"
            return resolved_mode

        if self._normalize_engine(current_db.get("ENGINE", "")) == "postgres":
            postgres_db = current_db
        else:
            postgres_db = self._default_postgres_config()

        postgres_db["ENGINE"] = "asyncpg"
        postgres_db["NAME"] = self._postgres_test_database_name(postgres_db.get("NAME", "neutronapi"))
        self._set_default_database(postgres_db)
        self._apply_postgres_runtime_env(postgres_db)
        self._active_database_config = deepcopy(settings.DATABASES["default"])

        if self._using_inherited_managed_postgres() and await self._has_existing_postgres_server(postgres_db):
            setup_databases(settings.DATABASES)
            self._active_database_config = deepcopy(settings.DATABASES["default"])
            self._selected_database = "postgres"
            return resolved_mode

        if not await self._has_existing_postgres_server(postgres_db):
            if verbosity > 0:
                print("Bootstrapping PostgreSQL container...")
            success = await self._bootstrap_postgres()
            if not success:
                success = await self._bootstrap_postgres_native()
            if not success:
                raise RuntimeError(
                    "Could not connect to PostgreSQL and both Docker and native bootstrap failed. "
                    "Configure a reachable PostgreSQL server, or install Docker or local PostgreSQL binaries."
                )
        else:
            await self._setup_test_database(postgres_db)
            self._apply_postgres_runtime_env(settings.DATABASES["default"])

        setup_databases(settings.DATABASES)
        self._active_database_config = deepcopy(settings.DATABASES["default"])
        self._selected_database = "postgres"
        return resolved_mode

    def _filter_suite_by_pattern(self, suite: unittest.TestSuite, pattern: str) -> unittest.TestSuite:
        """Filter test suite by pattern (-k option)."""
        filtered = unittest.TestSuite()

        for test in suite:
            if isinstance(test, unittest.TestSuite):
                nested = self._filter_suite_by_pattern(test, pattern)
                if nested.countTestCases():
                    filtered.addTests(nested)
                continue

            test_name = str(test)
            if fnmatch.fnmatch(test_name, f"*{pattern}*") or re.search(pattern, test_name):
                filtered.addTest(test)

        return filtered

    def _test_tags(self, test: unittest.case.TestCase) -> set[str]:
        test_method = getattr(test, test._testMethodName, None)
        tags = set()
        if test_method is not None:
            tags.update(getattr(test_method, "tags", []))
        tags.update(getattr(test.__class__, "tags", []))
        return tags

    def _filter_suite_by_tags(
        self,
        suite: unittest.TestSuite,
        include_tags: List[str],
        exclude_tags: List[str],
    ) -> unittest.TestSuite:
        """Filter test suite by tags."""
        if not include_tags and not exclude_tags:
            return suite

        filtered = unittest.TestSuite()
        include = set(include_tags)
        exclude = set(exclude_tags)

        for test in suite:
            if isinstance(test, unittest.TestSuite):
                nested = self._filter_suite_by_tags(test, include_tags, exclude_tags)
                if nested.countTestCases():
                    filtered.addTests(nested)
                continue

            test_tags = self._test_tags(test)
            if exclude and test_tags & exclude:
                continue
            if include and not (test_tags & include):
                continue
            filtered.addTest(test)

        return filtered

    def _should_include_test_for_provider(self, test: unittest.case.TestCase, database: str) -> bool:
        module_name = test.__class__.__module__.rsplit(".", 1)[-1]
        if "_postgres" in module_name:
            return database == "postgres"
        if "_sqlite" in module_name:
            return database == "sqlite"

        test_tags = self._test_tags(test)
        if database == "postgres" and "sqlite" in test_tags:
            return False
        if database == "sqlite" and "postgres" in test_tags:
            return False
        return True

    def _filter_suite_by_provider(self, suite: unittest.TestSuite, database: str) -> unittest.TestSuite:
        filtered = unittest.TestSuite()

        for test in suite:
            if isinstance(test, unittest.TestSuite):
                nested = self._filter_suite_by_provider(test, database)
                if nested.countTestCases():
                    filtered.addTests(nested)
                continue

            if self._should_include_test_for_provider(test, database):
                filtered.addTest(test)

        return filtered

    def _reverse_suite(self, suite: unittest.TestSuite) -> unittest.TestSuite:
        """Reverse the order of tests in suite."""
        tests = list(suite)
        tests.reverse()
        reversed_suite = unittest.TestSuite()

        for test in tests:
            if isinstance(test, unittest.TestSuite):
                reversed_suite.addTest(self._reverse_suite(test))
            else:
                reversed_suite.addTest(test)

        return reversed_suite

    def _iter_tests(self, suite: unittest.TestSuite) -> Iterable[unittest.case.TestCase]:
        for test in suite:
            if isinstance(test, unittest.TestSuite):
                yield from self._iter_tests(test)
            else:
                yield test

    async def _apply_project_migrations(self) -> None:
        try:
            base_dir = os.path.join(os.getcwd(), "apps")
            if not os.path.isdir(base_dir):
                return

            found_any = False
            for app_name in os.listdir(base_dir):
                mig_dir = os.path.join(base_dir, app_name, "migrations")
                if not os.path.isdir(mig_dir):
                    continue
                for filename in os.listdir(mig_dir):
                    if filename.endswith(".py") and filename[:3].isdigit():
                        found_any = True
                        break
                if found_any:
                    break

            if not found_any:
                return

            from neutronapi.db.connection import get_databases
            from neutronapi.db.migration_tracker import MigrationTracker

            tracker = MigrationTracker(base_dir="apps")
            connection = await get_databases().get_connection("default")
            await tracker.migrate(connection)
        except Exception:
            return

    async def _bootstrap_test_models(self) -> None:
        try:
            if not os.path.isdir("neutronapi") or not os.path.isfile("neutronapi/__init__.py"):
                return

            from neutronapi.db.connection import get_databases
            from neutronapi.db.migrations import CreateModel
            from neutronapi.tests.db.test_models import TestUser
            from neutronapi.tests.db.test_queryset import TestObject

            connection = await get_databases().get_connection("default")
            for model_cls in (TestUser, TestObject):
                create_operation = CreateModel(
                    f"neutronapi.{model_cls.__name__}",
                    model_cls._neutronapi_fields_,
                )
                await create_operation.database_forwards(
                    app_label="neutronapi",
                    provider=connection.provider,
                    from_state=None,
                    to_state=None,
                    connection=connection,
                )
        except Exception:
            return

    def _path_to_module(self, arg: str) -> str:
        if arg.endswith(".py"):
            arg = arg[:-3]
        arg = arg.lstrip("./")
        return arg.replace(os.sep, ".")

    def _add_target(self, loader: unittest.TestLoader, suite: unittest.TestSuite, target: str) -> None:
        if os.path.isdir(os.path.join("apps", target, "tests")):
            if "apps" not in sys.path:
                sys.path.insert(0, "apps")
            discovered = loader.discover(
                start_dir=os.path.join("apps", target, "tests"),
                pattern="test_*.py",
                top_level_dir="apps",
            )
            suite.addTests(discovered)
            return

        if target == "core" and os.path.isdir("core/tests"):
            suite.addTests(loader.discover("core/tests", pattern="test_*.py"))
            return

        if os.path.exists(target) and target.endswith(".py"):
            suite.addTests(loader.loadTestsFromName(self._path_to_module(target)))
            return

        if os.path.isdir("apps") and "apps" not in sys.path:
            sys.path.insert(0, "apps")

        if target.startswith("apps."):
            target = target[5:]

        suite.addTests(loader.loadTestsFromName(target))

    def _discover_tests(self, loader: unittest.TestLoader, test_targets: List[str]) -> unittest.TestSuite:
        suite = unittest.TestSuite()

        if test_targets:
            for target in test_targets:
                self._add_target(loader, suite, target)
            return suite

        test_dirs = []
        if os.path.isdir("core/tests"):
            test_dirs.append("core/tests")

        if os.path.isdir("apps"):
            if "apps" not in sys.path:
                sys.path.insert(0, "apps")
            for app_name in os.listdir("apps"):
                app_tests_dir = os.path.join("apps", app_name, "tests")
                if os.path.isdir(app_tests_dir):
                    test_dirs.append(app_tests_dir)

        if os.path.isdir("neutronapi/tests"):
            test_dirs.append("neutronapi/tests")

        if not test_dirs:
            return loader.discover(".", pattern="test_*.py")

        for test_dir in test_dirs:
            if test_dir.startswith("apps"):
                discovered = loader.discover(test_dir, pattern="test_*.py", top_level_dir="apps")
            else:
                discovered = loader.discover(test_dir, pattern="test_*.py")
            suite.addTests(discovered)
        return suite

    async def handle(self, args: List[str]) -> int:
        """Run tests with Django-like options."""
        parser = self._build_parser()
        try:
            options = parser.parse_args(args)
        except SystemExit as exc:
            return int(exc.code)

        if options.help_requested:
            print(self.help)
            return 0

        verbosity = 0 if options.quiet else options.verbosity
        failfast = options.failfast
        reverse = options.reverse
        pattern = options.pattern
        include_tags = options.tag
        exclude_tags = options.exclude_tag
        use_coverage = options.coverage
        debug_sql = options.debug_sql
        self._keepdb = options.keepdb
        test_targets = options.targets

        parallel: Optional[int] = None
        if options.parallel is not None:
            if options.parallel == "auto":
                parallel = os.cpu_count() or 4
            else:
                try:
                    parallel = int(options.parallel)
                except ValueError as exc:
                    raise ValueError(f"Invalid parallel worker count: {options.parallel}") from exc

        cov = None
        exit_code = 0

        try:
            selected_database = await self._configure_database_mode(options.database, verbosity)
            await self._apply_project_migrations()
            await self._bootstrap_test_models()

            if use_coverage or os.getenv("COVERAGE", "false").lower() == "true":
                try:
                    import coverage

                    cov = coverage.Coverage(source=["apps", "neutronapi"], branch=True)
                    cov.start()
                except Exception as exc:
                    if verbosity > 0:
                        print(f"Warning: coverage not started: {exc}")

            if debug_sql:
                import logging

                logging.getLogger("neutronapi.db").setLevel(logging.DEBUG)

            loader = unittest.TestLoader()
            suite = self._discover_tests(loader, test_targets)
            suite = self._filter_suite_by_provider(suite, selected_database)

            if pattern:
                suite = self._filter_suite_by_pattern(suite, pattern)
            if include_tags or exclude_tags:
                suite = self._filter_suite_by_tags(suite, include_tags, exclude_tags)
            if reverse:
                suite = self._reverse_suite(suite)

            count = suite.countTestCases()
            if count == 0:
                print("No tests found.")
                return 0

            if verbosity > 0:
                print(f"Running {count} test(s) against {selected_database}...")
                if pattern:
                    print(f"  Pattern: {pattern}")
                if include_tags:
                    print(f"  Tags: {', '.join(include_tags)}")
                if exclude_tags:
                    print(f"  Excluded tags: {', '.join(exclude_tags)}")

            stream = sys.stderr if verbosity > 0 else StringIO()
            runner = unittest.TextTestRunner(
                verbosity=verbosity,
                stream=stream,
                buffer=False,
                failfast=failfast,
            )

            if parallel and parallel > 1:
                if verbosity > 0:
                    print(f"Running tests in parallel ({parallel} workers)...")

                import concurrent.futures

                all_tests = list(self._iter_tests(suite))

                def run_single_test(test: unittest.case.TestCase) -> dict:
                    single_suite = unittest.TestSuite([test])
                    buffer = StringIO()
                    single_runner = unittest.TextTestRunner(
                        verbosity=0,
                        stream=buffer,
                        buffer=True,
                        failfast=False,
                    )
                    result = single_runner.run(single_suite)
                    return {
                        "test": str(test),
                        "success": result.wasSuccessful(),
                        "failures": len(result.failures),
                        "errors": len(result.errors),
                        "output": buffer.getvalue(),
                    }

                with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
                    future_to_test = {
                        executor.submit(run_single_test, test): test
                        for test in all_tests
                    }

                    passed = 0
                    failed = 0
                    errors = 0

                    for future in concurrent.futures.as_completed(future_to_test):
                        result = future.result()
                        if result["success"]:
                            passed += 1
                            if verbosity > 1:
                                print(f"  PASS: {result['test']}")
                        else:
                            if result["errors"]:
                                errors += result["errors"]
                                if verbosity > 0:
                                    print(f"  ERROR: {result['test']}")
                            else:
                                failed += result["failures"]
                                if verbosity > 0:
                                    print(f"  FAIL: {result['test']}")
                            if verbosity > 1:
                                print(result["output"])
                            if failfast:
                                executor.shutdown(wait=False)
                                break

                if verbosity > 0:
                    print(f"\n{passed} passed, {failed} failed, {errors} errors")
                exit_code = 0 if failed == 0 and errors == 0 else 1
            else:
                result = await asyncio.to_thread(runner.run, suite)
                if not result.wasSuccessful():
                    exit_code = 1
                    if verbosity > 0:
                        print(f"\n{len(result.failures)} failures, {len(result.errors)} errors")
                elif verbosity > 0:
                    print(f"\nAll {result.testsRun} tests passed!")

        except Exception as exc:
            print(f"Error running tests: {exc}")
            import traceback

            traceback.print_exc()
            exit_code = 1
        finally:
            if cov is not None:
                try:
                    cov.stop()
                    cov.save()
                    if verbosity > 0:
                        print("\nCoverage report:")
                        cov.report()
                    if os.getenv("COV_HTML", "false").lower() == "true":
                        cov.html_report(directory="htmlcov")
                except Exception:
                    pass

            try:
                await asyncio.wait_for(self.run_forced_shutdown(), timeout=3.0)
            except (asyncio.TimeoutError, Exception):
                pass

            try:
                await asyncio.wait_for(self._cleanup_test_database(), timeout=3.0)
            except (asyncio.TimeoutError, Exception):
                pass

            try:
                await asyncio.wait_for(self._teardown_postgres(), timeout=3.0)
            except (asyncio.TimeoutError, Exception):
                pass

        return exit_code


def tag(*tags):
    """Decorator to add tags to test methods or classes."""

    def decorator(obj):
        obj.tags = set(getattr(obj, "tags", set())) | set(tags)
        return obj

    return decorator
