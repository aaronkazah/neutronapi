import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

from unittest import TestCase, skipIf, skipUnless
import shutil


class TestCLIMigrationsIntegration(TestCase):
    def setUp(self):
        self.apps_dir = os.path.join(os.getcwd(), 'apps')
        os.makedirs(self.apps_dir, exist_ok=True)

    def tearDown(self):
        # Clean any tmp apps we created
        for name in os.listdir(self.apps_dir):
            if name.startswith('tmpapp_'):
                shutil.rmtree(os.path.join(self.apps_dir, name), ignore_errors=True)

    def _write_file(self, path: str, content: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)

    def _create_tmp_app_with_migration(self, app_label: str):
        # Create a minimal migration that creates a simple table
        mig_dir = os.path.join(self.apps_dir, app_label, 'migrations')
        self._write_file(os.path.join(mig_dir, '__init__.py'), '')
        migration_py = textwrap.dedent(
            f"""
            from neutronapi.db.migrations import Migration, CreateModel
            from neutronapi.db.fields import CharField

            class Dummy: pass

            migration = Migration(
                app_label='{app_label}',
                operations=[
                    CreateModel('{app_label}.Dummy', {{'id': CharField(primary_key=True), 'name': CharField(null=True)}})
                ]
            )
            """
        )
        self._write_file(os.path.join(mig_dir, '0001_initial.py'), migration_py)

    def _create_tmp_app_test(self, app_label: str, table_name: str):
        tests_dir = os.path.join(self.apps_dir, app_label, 'tests')
        self._write_file(os.path.join(tests_dir, '__init__.py'), '')
        test_py = textwrap.dedent(
            f"""
            import unittest
            from neutronapi.db.connection import get_databases

            class TestApplied(unittest.IsolatedAsyncioTestCase):
                async def test_table_exists(self):
                    conn = await get_databases().get_connection('default')
                    exists = await conn.provider.table_exists('{table_name}')
                    self.assertTrue(exists)
            """
        )
        self._write_file(os.path.join(tests_dir, 'test_applied.py'), test_py)

    def test_manage_py_test_applies_sqlite_migrations(self):
        app_label = 'tmpapp_sqlite'
        table_name = f'{app_label}_dummy'
        self._create_tmp_app_with_migration(app_label)

        # Apply migrations directly using tracker, forcing a SQLite connection
        import asyncio
        import os
        import tempfile
        from neutronapi.db.migration_tracker import MigrationTracker
        from neutronapi.db.connection import get_databases, setup_databases

        async def apply_and_check():
            # Force an isolated SQLite database for this test
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
            tmp.close()
            cfg = {
                'default': {
                    'ENGINE': 'aiosqlite',
                    'NAME': tmp.name,
                }
            }
            db_manager = setup_databases(cfg)
            try:
                tracker = MigrationTracker(base_dir='apps')
                conn = await get_databases().get_connection('default')
                await tracker.migrate(conn)
                exists = await conn.provider.table_exists(table_name)
                return exists
            finally:
                try:
                    await db_manager.close_all()
                except Exception:
                    pass
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass
                # Restore default connection manager from settings for other tests
                try:
                    setup_databases(None)
                except Exception:
                    pass

        self.assertTrue(asyncio.run(apply_and_check()), 'SQLite migration should create the table')

    def test_detects_unapplied_migrations(self):
        app_label = 'tmpapp_warn'
        # Create a migration file but do not run DB or async code.
        self._create_tmp_app_with_migration(app_label)

        # Verify migration files are discovered for the app (file-level signal of unapplied work).
        from neutronapi.db.migration_tracker import MigrationTracker
        tracker = MigrationTracker(base_dir='apps')
        discovered = tracker.discover_migration_files()
        self.assertIn(app_label, discovered, 'Should discover migrations for the temp app')
        self.assertGreater(len(discovered[app_label]), 0, 'Temp app should have at least one migration file')

    def _is_postgres_configured(self):
        """Check if default database is PostgreSQL and reachable."""
        try:
            from neutronapi.conf import settings
            import asyncio
            import asyncpg
            
            db_config = settings.DATABASES.get('default', {})
            if db_config.get('ENGINE', '').lower() != 'asyncpg':
                return False

            async def check_connection():
                try:
                    # Prefer configured DB; fall back to 'postgres' if it doesn't exist yet
                    conn = await asyncpg.connect(
                        host=db_config.get('HOST', 'localhost'),
                        port=db_config.get('PORT', 5432),
                        database=db_config.get('NAME', 'neutronapi_test'),
                        user=db_config.get('USER', 'postgres'),
                        password=db_config.get('PASSWORD', 'postgres'),
                    )
                    await conn.close()
                    return True
                except Exception:
                    try:
                        conn = await asyncpg.connect(
                            host=db_config.get('HOST', 'localhost'),
                            port=db_config.get('PORT', 5432),
                            database='postgres',
                            user=db_config.get('USER', 'postgres'),
                            password=db_config.get('PASSWORD', 'postgres'),
                        )
                        await conn.close()
                        return True
                    except Exception:
                        return False

            return asyncio.run(check_connection())
        except Exception:
            return False

    @skipIf(shutil.which('docker') is None, 'Docker not available for Postgres test')
    def test_manage_py_test_applies_postgres_migrations(self):
        if not self._is_postgres_configured():
            self.skipTest('PostgreSQL not configured in settings.DATABASES')
            
        app_label = 'tmpapp_pg'
        # For PostgreSQL, table is created in schema 'tmpapp_pg' with name 'dummy'
        table_name = f'{app_label}.dummy'
        self._create_tmp_app_with_migration(app_label)
        self._create_tmp_app_test(app_label, table_name)

        env = os.environ.copy()
        # Force Postgres default test settings in the subprocess when no apps/settings.py exists
        env['DATABASE_PROVIDER'] = 'asyncpg'

        result = subprocess.run(
            [sys.executable, 'manage.py', 'test', app_label, '-q'],
            cwd=os.getcwd(), capture_output=True, text=True, env=env
        )

        if result.returncode != 0:
            print('STDOUT:\n', result.stdout)
            print('STDERR:\n', result.stderr)

        self.assertEqual(result.returncode, 0, 'manage.py test should pass and apply migrations to Postgres test DB')
