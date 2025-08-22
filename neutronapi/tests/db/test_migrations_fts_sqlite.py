import unittest
import os
import tempfile

from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, TextField
from neutronapi.db.connection import setup_databases, get_databases
from neutronapi.db.migrations import CreateModel


class Post(Model):
    title = CharField()
    body = TextField()

    class Meta:
        search_fields = ("title", "body")
        sqlite_fts = True


class TestMigrationsFTSSQLite(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        if hasattr(self, 'db_manager'):
            await self.db_manager.close_all()
        if hasattr(self, 'temp_db') and self.temp_db:
            try:
                os.unlink(self.temp_db.name)
            except Exception:
                pass

    async def test_create_model_sets_up_fts5(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        cfg = {
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': self.temp_db.name,
            }
        }
        self.db_manager = setup_databases(cfg)
        conn = await get_databases().get_connection('default')

        # Build search_meta from Meta
        search_meta = {
            'search_fields': getattr(Post.Meta, 'search_fields', ("title", "body")),
            'sqlite_fts': getattr(Post.Meta, 'sqlite_fts', True),
        }

        op = CreateModel('neutronapi.Post', Post._fields, search_meta=search_meta)
        await op.database_forwards('neutronapi', conn.provider, None, None, conn)

        base_table = Post.get_table_name()
        fts_table = f"{base_table}_fts"
        row = await conn.fetch_one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (fts_table,))
        self.assertIsNotNone(row)

