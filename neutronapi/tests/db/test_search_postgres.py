import os
import unittest

from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, TextField
from neutronapi.db.connection import setup_databases, get_databases


@unittest.skipUnless(os.getenv('DATABASE_PROVIDER', '').lower() == 'asyncpg', 'PostgreSQL tests disabled (set DATABASE_PROVIDER=asyncpg)')
class TestSearchPostgres(unittest.IsolatedAsyncioTestCase):
    class TestDoc(Model):
        key = CharField(null=False)
        title = CharField(null=True)
        body = TextField(null=True)

    async def asyncSetUp(self):
        # Use environment-backed Postgres config similar to other PG tests
        db_name = os.getenv('PGDATABASE', 'temp_db')
        db_host = os.getenv('PGHOST', 'localhost')
        db_port = int(os.getenv('PGPORT', '5432'))
        db_user = os.getenv('PGUSER', 'postgres')
        db_pass = os.getenv('PGPASSWORD', '')
        cfg = {
            'default': {
                'ENGINE': 'asyncpg',
                'NAME': db_name,
                'HOST': db_host,
                'PORT': db_port,
                'USER': db_user,
                'PASSWORD': db_pass,
                'OPTIONS': {
                    # Allow specifying a text search config through env if desired
                    'TSVECTOR_CONFIG': os.getenv('PG_TSVECTOR_CONFIG'),
                }
            }
        }
        self.db_manager = setup_databases(cfg)

        # Create table via migrations
        from neutronapi.db.migrations import CreateModel
        conn = await get_databases().get_connection('default')
        op = CreateModel('neutronapi.TestSearchPostgres_TestDoc', self.TestDoc._fields)
        await op.database_forwards(
            app_label='neutronapi',
            provider=conn.provider,
            from_state=None,
            to_state=None,
            connection=conn,
        )

    async def asyncTearDown(self):
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
