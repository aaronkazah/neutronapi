import os
import unittest

from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, TextField
from neutronapi.db.connection import setup_databases, get_databases
from neutronapi.db.migrations import CreateModel


@unittest.skipUnless(os.getenv('DATABASE_PROVIDER', '').lower() == 'asyncpg', 'PostgreSQL tests disabled (set DATABASE_PROVIDER=asyncpg)')
class TestMigrationsFTSPostgres(unittest.IsolatedAsyncioTestCase):
    class Post(Model):
        title = CharField()
        body = TextField()

        class Meta:
            search_fields = ("title", "body")
            search_config = os.getenv('PG_TSVECTOR_CONFIG') or 'english'

    async def asyncSetUp(self):
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
            }
        }
        self.db_manager = setup_databases(cfg)
        self.conn = await get_databases().get_connection('default')

    async def asyncTearDown(self):
        await self.db_manager.close_all()

    async def test_create_model_sets_up_tsvector(self):
        search_meta = {
            'search_fields': getattr(self.Post.Meta, 'search_fields', ("title", "body")),
            'search_config': getattr(self.Post.Meta, 'search_config', None),
        }
        op = CreateModel('neutronapi.Post', self.Post._fields, search_meta=search_meta)
        await op.database_forwards('neutronapi', self.conn.provider, None, None, self.conn)

        schema, table = self.Post._get_parsed_table_name()
        # Verify tsvector column exists
        row = await self.conn.fetch_one(
            "SELECT 1 FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2 AND column_name='search_vector'",
            (schema, table),
        )
        self.assertIsNotNone(row)

