import os
import tempfile
import textwrap
import shutil
import unittest
import importlib

from neutronapi.db.migrations import MigrationManager
from neutronapi.db.connection import get_databases


class TestMigrationsPostgres(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from neutronapi.conf import settings
        # Ensure we are configured for Postgres and can reach it
        db_config = settings.DATABASES.get('default', {})
        if db_config.get('ENGINE', '').lower() != 'asyncpg':
            self.skipTest('PostgreSQL not configured in settings.DATABASES')
        try:
            import asyncpg
            conn0 = await asyncpg.connect(
                host=db_config.get('HOST', 'localhost'),
                port=db_config.get('PORT', 5432),
                database='postgres',
                user=db_config.get('USER', 'postgres'),
                password=db_config.get('PASSWORD', 'postgres'),
            )
            await conn0.close()
        except Exception:
            self.skipTest('PostgreSQL server not reachable')

        import sys, importlib
        self.tmpdir = tempfile.mkdtemp()
        self.apps_dir = os.path.join(self.tmpdir, 'apps')
        os.makedirs(self.apps_dir, exist_ok=True)

        app = 'testapp_pg'
        self.app_dir = os.path.join(self.apps_dir, app)
        models_dir = os.path.join(self.app_dir, 'models')
        migrations_dir = os.path.join(self.app_dir, 'migrations')
        os.makedirs(models_dir)
        os.makedirs(migrations_dir)
        for p in (self.app_dir, models_dir, migrations_dir):
            with open(os.path.join(p, '__init__.py'), 'w') as f:
                f.write("")

        with open(os.path.join(models_dir, 'user.py'), 'w') as f:
            f.write(textwrap.dedent(
                """
                from neutronapi.db.models import Model
                from neutronapi.db.fields import CharField, IntegerField

                class User(Model):
                    name = CharField(max_length=100)
                    age = IntegerField(null=True)
                """
            ))

        # Ensure temp apps dir is importable
        if self.apps_dir not in sys.path:
            sys.path.insert(0, self.apps_dir)
        importlib.invalidate_caches()

        # Ensure we're using PostgreSQL, not any SQLite config that other tests might have set
        from neutronapi.conf import settings
        if not hasattr(settings, 'DATABASES') or 'default' not in settings.DATABASES:
            self.skipTest('PostgreSQL not configured in settings')
        
        # Force setup with PostgreSQL configuration
        from neutronapi.db.connection import setup_databases
        setup_databases()
        
        conn = await get_databases().get_connection('default') 
        self.provider = conn.provider
        # Verify we got the right provider
        if 'SQLite' in type(self.provider).__name__:
            self.skipTest('Expected PostgreSQL provider but got SQLite - database configuration was overridden by another test')

    async def asyncTearDown(self):
        shutil.rmtree(self.tmpdir)

    async def test_make_and_apply_migration_pg(self):
        import sys
        importlib.invalidate_caches()
        # Ensure our temp apps dir is importable for module discovery
        if self.apps_dir not in sys.path:
            sys.path.insert(0, self.apps_dir)
        app_label = 'testapp_pg'
        manager = MigrationManager(apps=[app_label], base_dir=self.apps_dir)
        models = manager._discover_models(app_label)
        self.assertTrue(models)
        ops = await manager.makemigrations(app_label, models=models, return_ops=True, clean=True)
        self.assertTrue(ops)
        await manager.migrate(app_label, self.provider, operations=ops)
        exists = await self.provider.table_exists(f'{app_label}.user')
        self.assertTrue(exists)
