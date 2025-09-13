import unittest

from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, TextField
from neutronapi.db.connection import setup_databases, get_databases
from neutronapi.db.migrations import CreateModel


def _is_postgres_configured():
    """Check if default database is configured for PostgreSQL and accessible."""
    try:
        from neutronapi.conf import settings
        import asyncio
        import asyncpg
        
        db_config = settings.DATABASES.get('default', {})
        if db_config.get('ENGINE', '').lower() != 'asyncpg':
            return False
            
        # Try to connect to verify PostgreSQL is actually available
        async def check_connection():
            try:
                conn = await asyncpg.connect(
                    host=db_config.get('HOST', 'localhost'),
                    port=db_config.get('PORT', 5432),
                    database='postgres',
                    user=db_config.get('USER', 'postgres'),
                    password=db_config.get('PASSWORD', 'postgres'),
                )
                await conn.close()
                return True
            except:
                return False
        
        return asyncio.run(check_connection())
    except:
        return False


@unittest.skipUnless(_is_postgres_configured(), 'PostgreSQL not configured in settings.DATABASES')
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

