import os
import tempfile
import unittest

from neutronapi.db.models import Model
from neutronapi.db.fields import CharField
from neutronapi.db.connection import setup_databases


class AwaitUser(Model):
    name = CharField(null=False)


class TestQuerySetAwaitBehavior(unittest.IsolatedAsyncioTestCase):
    def _should_skip_for_provider(self):
        """Skip SQLite-specific tests when running with non-SQLite providers"""
        import os
        provider = os.environ.get('DATABASE_PROVIDER', '').lower()
        if provider in ('asyncpg', 'postgres', 'postgresql'):
            self.skipTest('SQLite-specific test skipped when running with PostgreSQL provider')
    
    async def asyncSetUp(self):
        self._should_skip_for_provider()
        
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        db_config = {
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': self.temp_db.name,
            }
        }
        self.db_manager = setup_databases(db_config)

        # Create table via migration op
        from neutronapi.db.migrations import CreateModel
        connection = await self.db_manager.get_connection()
        op = CreateModel('neutronapi.AwaitUser', AwaitUser._neutronapi_fields_)
        await op.database_forwards(
            app_label='neutronapi',
            provider=connection.provider,
            from_state=None,
            to_state=None,
            connection=connection,
        )

        # Seed rows
        await AwaitUser.objects.create(id='u1', name='A')
        await AwaitUser.objects.create(id='u2', name='B')

    async def asyncTearDown(self):
        await self.db_manager.close_all()
        try:
            os.unlink(self.temp_db.name)
        except Exception:
            pass

    async def test_await_queryset_returns_queryset_and_methods_work(self):
        qs = AwaitUser.objects.filter(name='A')

        # Awaiting the queryset should return the same queryset (with cache populated)
        awaited = await qs
        self.assertIs(awaited, qs)

        # Iteration works after awaiting (cache populated)
        items = list(awaited)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, 'A')

        # Can call further async methods on the awaited queryset (e.g., delete)
        await awaited.delete()
        count = await AwaitUser.objects.count()
        self.assertEqual(count, 1)

    async def test_await_objects_property_returns_queryset(self):
        # Awaiting the manager-backed queryset returns a queryset with methods
        qs = await AwaitUser.objects
        self.assertTrue(hasattr(qs, 'delete'))
        # Iteration works after awaiting
        all_items = list(qs)
        # Two seeded rows at setup time
        self.assertEqual(len(all_items), 2)
