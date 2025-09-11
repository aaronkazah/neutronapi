import unittest

from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, TextField
from neutronapi.db.connection import setup_databases, get_databases


class TestSearchPostgres(unittest.IsolatedAsyncioTestCase):
    class TestDoc(Model):
        key = CharField(null=False)
        title = CharField(null=True)
        body = TextField(null=True)

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

        # Verify server reachability
        try:
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

        # Use existing settings.DATABASES configuration
        self.db_manager = setup_databases()

        # Create table via migrations
        from neutronapi.db.migrations import CreateModel
        conn = await get_databases().get_connection('default')
        # Ensure table name matches Model.get_table_name() -> neutronapi_test_doc
        op = CreateModel('neutronapi.TestDoc', self.TestDoc._fields)
        await op.database_forwards(
            app_label='neutronapi',
            provider=conn.provider,
            from_state=None,
            to_state=None,
            connection=conn,
        )

    async def asyncTearDown(self):
        # Clean up test data before closing connections
        try:
            await self.TestDoc.objects.all().delete()
        except Exception:
            pass
        await self.db_manager.close_all()

    async def test_full_text_search_matches(self):
        # Insert test docs
        await self.TestDoc.objects.create(id='p1', key='k1', title='Alpha', body='some body')
        await self.TestDoc.objects.create(id='p2', key='k2', title='beta', body='Alpha in body')

        # Search should find both via Postgres FTS
        res = await self.TestDoc.objects.search('alpha').values_list('id')
        ids = [r[0] for r in list(res)]
        self.assertCountEqual(ids, ['p1', 'p2'])

    async def test_full_text_order_by_rank(self):
        # Insert docs with varying relevance
        await self.TestDoc.objects.create(id='rp1', key='rk1', title='alpha alpha', body='')
        await self.TestDoc.objects.create(id='rp2', key='rk2', title='alpha', body='')

        res = await self.TestDoc.objects.search('alpha').order_by_rank().values_list('id')
        ids = [r[0] for r in list(res)]
        # Expect the document with repeated term to rank higher (first)
        self.assertEqual(ids[0], 'rp1')
