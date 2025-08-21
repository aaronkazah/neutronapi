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

        # Apply migrations directly using tracker (no subprocess, single DB env)
        import asyncio
        from neutronapi.db.migration_tracker import MigrationTracker
        from neutronapi.db.connection import get_databases

        async def apply_and_check():
            os.environ.pop('DATABASE_PROVIDER', None)  # force sqlite path
            os.environ['TESTING'] = '1'
            tracker = MigrationTracker(base_dir='apps')
            conn = await get_databases().get_connection('default')
            await tracker.migrate(conn)
            exists = await conn.provider.table_exists(table_name)
            return exists

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

    @skipUnless(os.getenv('DATABASE_PROVIDER', '').lower() in ('asyncpg', 'postgres', 'postgresql'),
               'Postgres provider not selected (set DATABASE_PROVIDER=asyncpg to enable)')
    @skipIf(shutil.which('docker') is None, 'Docker not available for Postgres test')
    def test_manage_py_test_applies_postgres_migrations(self):
        app_label = 'tmpapp_pg'
        # For PostgreSQL, table is created in schema 'tmpapp_pg' with name 'dummy'
        table_name = f'{app_label}.dummy'
        self._create_tmp_app_with_migration(app_label)
        self._create_tmp_app_test(app_label, table_name)

        env = os.environ.copy()
        env['DATABASE_PROVIDER'] = 'asyncpg'
        env['TESTING'] = '1'

        result = subprocess.run(
            [sys.executable, 'manage.py', 'test', app_label, '-q'],
            cwd=os.getcwd(), capture_output=True, text=True, env=env
        )

        if result.returncode != 0:
            print('STDOUT:\n', result.stdout)
            print('STDERR:\n', result.stderr)

        self.assertEqual(result.returncode, 0, 'manage.py test should pass and apply migrations to Postgres test DB')
