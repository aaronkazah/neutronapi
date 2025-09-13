import unittest
import os
import tempfile

from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, TextField
from neutronapi.db.connection import setup_databases, get_databases
from neutronapi.db.migrations import CreateModel


class Note(Model):
    title = CharField()
    body = TextField()


class TestMigrationsFTSSQLiteDefault(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        if hasattr(self, 'db_manager'):
            await self.db_manager.close_all()
        if hasattr(self, 'temp_db') and self.temp_db:
            try:
                os.unlink(self.temp_db.name)
            except Exception:
                pass

    async def test_default_infers_and_creates_fts(self):
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

        # No search_meta provided -> defaults inferred and FTS should be created
        op = CreateModel('neutronapi.Note', Note._neutronapi_fields_)
        await op.database_forwards('neutronapi', conn.provider, None, None, conn)

        base_table = Note.get_table_name()
        fts_table = f"{base_table}_fts"
        row = await conn.fetch_one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (fts_table,))
        self.assertIsNotNone(row)

