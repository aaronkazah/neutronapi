import unittest
import os
import tempfile

from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, TextField, JSONField
from neutronapi.db.connection import setup_databases, get_databases


class TestDoc(Model):
    key = CharField(null=False)
    name = CharField(null=True)
    body = TextField(null=True)
    meta = JSONField(null=True, default=dict)


class TestSearchSQLite(unittest.IsolatedAsyncioTestCase):
    def _should_skip_for_provider(self):
        """Skip SQLite-specific tests when running with non-SQLite providers"""
        import os
        provider = os.environ.get('DATABASE_PROVIDER', '').lower()
        if provider in ('asyncpg', 'postgres', 'postgresql'):
            self.skipTest('SQLite-specific test skipped when running with PostgreSQL provider')
            
    async def asyncTearDown(self):
        if hasattr(self, 'db_manager'):
            await self.db_manager.close_all()
        if hasattr(self, 'temp_db') and self.temp_db:
            try:
                os.unlink(self.temp_db.name)
            except Exception:
                pass

    async def _create_table(self):
        from neutronapi.db.migrations import CreateModel
        connection = await self.db_manager.get_connection('default')
        op = CreateModel('neutronapi.TestDoc', TestDoc._fields)
        await op.database_forwards(
            app_label='neutronapi',
            provider=connection.provider,
            from_state=None,
            to_state=None,
            connection=connection,
        )

    async def test_search_like_fallback_sqlite(self):
        self._should_skip_for_provider()
        # Setup SQLite without FTS configuration -> LIKE fallback
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        db_config = {
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': self.temp_db.name,
            }
        }
        self.db_manager = setup_databases(db_config)
        await self._create_table()

        # Insert docs
        await TestDoc.objects.create(id='d1', key='k1', name='Alpha', body='something', meta={})
        await TestDoc.objects.create(id='d2', key='k2', name='Beta', body='lorem alpha ipsum', meta={})

        # Fallback LIKE should find both by substring
        results = await TestDoc.objects.search('alpha').values_list('id', 'name')
        rows = list(results)
        self.assertEqual(len(rows), 2)
        self.assertCountEqual([r[0] for r in rows], ['d1', 'd2'])

    async def test_search_sqlite_fts5_match(self):
        self._should_skip_for_provider()
        # Setup SQLite with FTS5 configuration
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        db_config = {
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': self.temp_db.name,
                'OPTIONS': {
                    'FTS': {},  # enables default <table>_fts name
                },
            }
        }
        self.db_manager = setup_databases(db_config)
        await self._create_table()

        # Insert a base row that does NOT contain the term in base columns
        await TestDoc.objects.create(id='d3', key='k3', name='Nope', body='', meta={})

        # Create FTS table and populate with rowid-mapped content containing the term
        conn = await get_databases().get_connection('default')
        base_table = TestDoc.get_table_name()
        fts_table = f"{base_table}_fts"

        # Create FTS5 table with columns matching searchable fields
        await conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS \"{fts_table}\" USING fts5(name, body)")

        # Fetch rowid for the inserted base row
        row = await conn.fetch_one(f"SELECT rowid FROM \"{base_table}\" WHERE id=?", ('d3',))
        self.assertIsNotNone(row)
        rowid = list(row.values())[0] if isinstance(row, dict) else row[0]

        # Insert FTS content for that rowid that includes the term 'needle'
        await conn.execute(f"INSERT INTO \"{fts_table}\"(rowid, name, body) VALUES (?,?,?)", (rowid, 'needle here', ''))

        # Now full-text search should find the row via MATCH path
        res = await TestDoc.objects.search('needle').values_list('id', 'name')
        found = list(res)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 'd3')

    async def test_search_sqlite_fts5_order_by_rank(self):
        self._should_skip_for_provider()
        # Setup SQLite with FTS5 configuration
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        db_config = {
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': self.temp_db.name,
                'OPTIONS': {
                    'FTS': {},
                },
            }
        }
        self.db_manager = setup_databases(db_config)
        await self._create_table()

        # Two docs both matching the term, one with higher relevance (more occurrences)
        await TestDoc.objects.create(id='r1', key='kr1', name='needle', body='needle needle needle')
        await TestDoc.objects.create(id='r2', key='kr2', name='needle', body='needle')

        # Create FTS table and populate with content mirroring searchable fields
        conn = await get_databases().get_connection('default')
        base_table = TestDoc.get_table_name()
        fts_table = f"{base_table}_fts"
        await conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS \"{fts_table}\" USING fts5(name, body)")
        # Insert FTS rows for both base rows
        rows = await conn.fetch_all(f"SELECT rowid, id, name, body FROM \"{base_table}\" WHERE id IN (?,?)", ('r1', 'r2'))
        for r in rows:
            rd = dict(r)
            await conn.execute(
                f"INSERT INTO \"{fts_table}\"(rowid, name, body) VALUES (?,?,?)",
                (rd['rowid'], rd['name'], rd['body'])
            )

        # Order by rank should place 'r1' (more occurrences) before 'r2'
        res = await TestDoc.objects.search('needle').order_by_rank().values_list('id')
        ids = [row[0] for row in list(res)]
        self.assertEqual(ids[0], 'r1')
