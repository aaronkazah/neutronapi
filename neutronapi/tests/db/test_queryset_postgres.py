import unittest
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, JSONField
from neutronapi.db.connection import get_databases


class TestQuerySetPostgres(unittest.IsolatedAsyncioTestCase):
    class TestItem(Model):
        id = CharField(primary_key=True)
        name = CharField()
        meta = JSONField()

        class Meta:
            table_name = 'test_items_pg'

    async def asyncSetUp(self):
        from neutronapi.conf import settings
        # Require Postgres engine
        db_config = settings.DATABASES.get('default', {})
        if db_config.get('ENGINE', '').lower() != 'asyncpg':
            self.skipTest('PostgreSQL not configured in settings.DATABASES')

        try:
            import asyncpg
        except Exception:
            self.skipTest('asyncpg not installed')

        # Ensure test database exists and is reachable
        test_db_name = db_config.get('NAME', 'neutronapi_test')
        if not test_db_name.startswith('test_'):
            test_db_name = f'test_{test_db_name}'
            settings._settings['DATABASES']['default']['NAME'] = test_db_name

        try:
            admin_conn = await asyncpg.connect(
                host=db_config.get('HOST', 'localhost'),
                port=db_config.get('PORT', 5432),
                database='postgres',
                user=db_config.get('USER', 'postgres'),
                password=db_config.get('PASSWORD', 'postgres'),
            )
            try:
                await admin_conn.execute(f'CREATE DATABASE "{test_db_name}"')
            finally:
                await admin_conn.close()
        except Exception:
            # If we cannot reach server, skip
            self.skipTest('PostgreSQL server not reachable')

        # Connect and prepare table
        conn = await get_databases().get_connection('default')
        self.provider = conn.provider
        await self.provider.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.TestItem.get_table_name()} (
                id TEXT PRIMARY KEY,
                name TEXT,
                meta JSONB
            )
        """)
        await self.provider.execute(f"DELETE FROM {self.TestItem.get_table_name()}")

    async def asyncTearDown(self):
        # Clean up test table
        await self.provider.execute(f"DROP TABLE IF EXISTS {self.TestItem.get_table_name()}")

    async def test_queryset_pg(self):
        # Create test data using the model
        await self.TestItem.objects.create(id="item-1", name="A", meta={"tag": "alpha"})
        await self.TestItem.objects.create(id="item-2", name="B", meta={"tag": "beta"})

        # Test QuerySet operations
        count = await self.TestItem.objects.count()
        self.assertEqual(count, 2)
        
        alpha = await self.TestItem.objects.filter(meta__tag__exact='alpha').first()
        self.assertIsNotNone(alpha)
        self.assertEqual(alpha.name, 'A')
