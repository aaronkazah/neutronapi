import os
import tempfile
import textwrap
import shutil
import unittest
import importlib

from neutronapi.db.migrations import MigrationManager
from neutronapi.db.connection import get_databases


@unittest.skipUnless(os.getenv('DATABASE_PROVIDER', '').lower() == 'asyncpg', 'PostgreSQL tests disabled (set DATABASE_PROVIDER=asyncpg)')
class TestMigrationsPostgres(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import sys, importlib
        self.tmpdir = tempfile.mkdtemp()
        self.apps_dir = os.path.join(self.tmpdir, 'apps')
        os.makedirs(self.apps_dir, exist_ok=True)

        app = 'testapp'
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

        conn = await get_databases().get_connection('default')
        self.provider = conn.provider

    async def asyncTearDown(self):
        shutil.rmtree(self.tmpdir)

    async def test_make_and_apply_migration_pg(self):
        import sys
        importlib.invalidate_caches()
        # Ensure our temp apps dir is importable for module discovery
        if self.apps_dir not in sys.path:
            sys.path.insert(0, self.apps_dir)
        manager = MigrationManager(apps=['testapp'], base_dir=self.apps_dir)
        models = manager._discover_models('testapp')
        self.assertTrue(models)
        ops = await manager.makemigrations('testapp', models=models, return_ops=True, clean=True)
        self.assertTrue(ops)
        await manager.migrate('testapp', self.provider, operations=ops)
        exists = await self.provider.table_exists('testapp.user')
        self.assertTrue(exists)
