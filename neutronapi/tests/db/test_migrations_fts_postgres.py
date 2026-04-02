import unittest

from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, TextField
from neutronapi.db.connection import setup_databases, get_databases
from neutronapi.db.migrations import CreateModel


class TestMigrationsFTSPostgres(unittest.IsolatedAsyncioTestCase):
    class Post(Model):
        title = CharField()
        body = TextField()

        class Meta:
            search_fields = ("title", "body")
            search_config = 'english'

    async def asyncSetUp(self):
        # Use existing settings.DATABASES configuration
        self.db_manager = setup_databases()
        self.conn = await get_databases().get_connection('default')

    async def asyncTearDown(self):
        await self.db_manager.close_all()

    async def test_create_model_sets_up_tsvector(self):
        search_meta = {
            'search_fields': getattr(self.Post.Meta, 'search_fields', ("title", "body")),
            'search_config': getattr(self.Post.Meta, 'search_config', None),
        }
        op = CreateModel('neutronapi.Post', self.Post._neutronapi_fields_, search_meta=search_meta)
        await op.database_forwards('neutronapi', self.conn.provider, None, None, self.conn)

        schema, table = self.Post._get_parsed_table_name()
        # Verify tsvector column exists
        row = await self.conn.fetch_one(
            "SELECT 1 FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2 AND column_name='search_vector'",
            (schema, table),
        )
        self.assertIsNotNone(row)
