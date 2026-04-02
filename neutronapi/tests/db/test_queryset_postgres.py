import unittest
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, JSONField
from neutronapi.db.connection import get_databases, setup_databases


class TestQuerySetPostgres(unittest.IsolatedAsyncioTestCase):
    class TestItem(Model):
        id = CharField(primary_key=True)
        name = CharField()
        meta = JSONField()

        class Meta:
            table_name = 'test_items_pg'

    async def asyncSetUp(self):
        self.db_manager = setup_databases()
        conn = await get_databases().get_connection('default')
        self.provider = conn.provider
        schema, table = self.TestItem._get_parsed_table_name()
        table_identifier = self.provider.get_table_identifier(schema, table)
        await self.provider.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        await self.provider.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_identifier} (
                id TEXT PRIMARY KEY,
                name TEXT,
                meta JSONB
            )
        """)
        await self.provider.execute(f"DELETE FROM {table_identifier}")

    async def asyncTearDown(self):
        # Clean up test table
        schema, table = self.TestItem._get_parsed_table_name()
        table_identifier = self.provider.get_table_identifier(schema, table)
        await self.provider.execute(f"DROP TABLE IF EXISTS {table_identifier}")
        await self.db_manager.close_all()

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
