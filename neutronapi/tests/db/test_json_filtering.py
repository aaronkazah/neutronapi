"""
Test cases for JSON field filtering with key lookups.

This tests the ORM's ability to filter JSON fields using key-based lookups
like _fields__account='value'. PostgreSQL supports this natively, SQLite should too.
"""

import unittest
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, JSONField, IntegerField
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
            except Exception:
                return False

        # Handle event loop issues properly
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If there's already a running loop, we can't use asyncio.run()
                # This happens during test execution
                return True  # Assume it's configured if we can't test
            else:
                return asyncio.run(check_connection())
        except RuntimeError:
            # No event loop, safe to create one
            return asyncio.run(check_connection())
    except Exception:
        return False


class JsonTestModel(Model):
    """Test model with JSON field for filtering tests."""

    name = CharField(max_length=100)
    data = JSONField(default=dict)
    count = IntegerField(default=0)


class TestJSONFiltering(unittest.IsolatedAsyncioTestCase):
    """Test JSON field filtering with key-based lookups."""

    async def asyncSetUp(self):
        """Set up test database and table."""
        # Will be overridden by test runner to use SQLite or PostgreSQL
        setup_databases({
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': ':memory:',
            }
        })

        self.connection = await get_databases().get_connection('default')

        # Create table
        op = CreateModel('neutronapi.JsonTestModel', JsonTestModel._neutronapi_fields_)
        await op.database_forwards('neutronapi', self.connection.provider, None, None, self.connection)

        # Create test data with varied JSON structures
        await JsonTestModel.objects.create(
            name='user1',
            data={'account': 'test_account', 'role': 'admin', 'active': True, 'count': 3},
            count=1
        )
        await JsonTestModel.objects.create(
            name='user2',
            data={'account': 'other_account', 'role': 'user', 'active': False, 'count': 1},
            count=2
        )
        await JsonTestModel.objects.create(
            name='user3',
            data={'role': 'guest', 'active': True, 'count': 2},  # No account key
            count=3
        )
        await JsonTestModel.objects.create(
            name='user4',
            data={'account': 'test_account', 'role': 'user', 'department': 'engineering', 'count': 4},
            count=4
        )

    async def test_json_key_filtering_exact(self):
        """Test filtering JSON field by key with exact value."""
        # Filter by account key
        results = await JsonTestModel.objects.filter(data__account='test_account')
        results_list = list(results)

        self.assertEqual(len(results_list), 2)
        names = {r.name for r in results_list}
        self.assertEqual(names, {'user1', 'user4'})

    async def test_json_key_filtering_different_values(self):
        """Test filtering JSON field by key with different values."""
        # Filter by different account value
        results = await JsonTestModel.objects.filter(data__account='other_account')
        results_list = list(results)

        self.assertEqual(len(results_list), 1)
        self.assertEqual(results_list[0].name, 'user2')

    async def test_json_key_filtering_nonexistent_key(self):
        """Test filtering by key that doesn't exist in all records."""
        # Filter by department key (only exists in user4)
        results = await JsonTestModel.objects.filter(data__department='engineering')
        results_list = list(results)

        self.assertEqual(len(results_list), 1)
        self.assertEqual(results_list[0].name, 'user4')

    async def test_json_key_filtering_boolean(self):
        """Test filtering JSON field by boolean value."""
        # Filter by active boolean
        results = await JsonTestModel.objects.filter(data__active=True)
        results_list = list(results)

        self.assertEqual(len(results_list), 2)
        names = {r.name for r in results_list}
        self.assertEqual(names, {'user1', 'user3'})

    async def test_json_key_filtering_nonexistent_value(self):
        """Test filtering by value that doesn't exist."""
        results = await JsonTestModel.objects.filter(data__account='nonexistent')
        results_list = list(results)

        self.assertEqual(len(results_list), 0)

    async def test_multiple_json_key_filters(self):
        """Test filtering by multiple JSON keys."""
        # Filter by account AND role
        results = await JsonTestModel.objects.filter(
            data__account='test_account',
            data__role='admin'
        )
        results_list = list(results)

        self.assertEqual(len(results_list), 1)
        self.assertEqual(results_list[0].name, 'user1')

    async def test_json_key_with_other_field_filters(self):
        """Test combining JSON key filters with regular field filters."""
        # Filter by JSON key AND regular field
        results = await JsonTestModel.objects.filter(
            data__account='test_account',
            count__gt=3
        )
        results_list = list(results)

        self.assertEqual(len(results_list), 1)
        self.assertEqual(results_list[0].name, 'user4')

    async def test_json_exact_vs_key_filtering(self):
        """Test difference between exact JSON matching and key filtering."""
        # Exact JSON matching - must match entire object
        results_exact = await JsonTestModel.objects.filter(
            data={'account': 'test_account', 'role': 'admin', 'active': True, 'count': 3}
        )
        exact_list = list(results_exact)
        self.assertEqual(len(exact_list), 1)
        self.assertEqual(exact_list[0].name, 'user1')

        # Key filtering - matches any object with that key-value pair
        results_key = await JsonTestModel.objects.filter(data__account='test_account')
        key_list = list(results_key)
        self.assertEqual(len(key_list), 2)
        names = {r.name for r in key_list}
        self.assertEqual(names, {'user1', 'user4'})

    async def test_json_ordering_by_key(self):
        """Test ordering by JSON field keys."""
        # Test ordering by count field (numeric)
        results = await JsonTestModel.objects.order_by('data__count')
        results_list = list(results)

        # Should be ordered by count: 1, 2, 3, 4
        expected_order = ['user2', 'user3', 'user1', 'user4']
        actual_order = [r.name for r in results_list]
        self.assertEqual(actual_order, expected_order)

        # Test reverse ordering
        results = await JsonTestModel.objects.order_by('-data__count')
        results_list = list(results)

        # Should be reverse: 4, 3, 2, 1
        expected_order = ['user4', 'user1', 'user3', 'user2']
        actual_order = [r.name for r in results_list]
        self.assertEqual(actual_order, expected_order)

    async def test_json_ordering_by_string_key(self):
        """Test ordering by JSON string field keys."""
        # Test ordering by role field (string)
        results = await JsonTestModel.objects.order_by('data__role')
        results_list = list(results)

        # Should be ordered alphabetically: admin, guest, user, user
        roles = [r.data['role'] for r in results_list]
        self.assertEqual(roles, ['admin', 'guest', 'user', 'user'])


@unittest.skipUnless(_is_postgres_configured(), 'PostgreSQL not configured in settings.DATABASES')
class TestJSONFilteringPostgreSQL(TestJSONFiltering):
    """Test JSON filtering with PostgreSQL provider."""

    async def asyncSetUp(self):
        """Set up PostgreSQL test database."""
        from neutronapi.tests.test_utils import get_postgres_test_config
        setup_databases({
            'default': get_postgres_test_config()
        })

        self.connection = await get_databases().get_connection('default')

        # Create table
        op = CreateModel('neutronapi.JsonTestModel', JsonTestModel._neutronapi_fields_)
        await op.database_forwards('neutronapi', self.connection.provider, None, None, self.connection)

        # Create test data with varied JSON structures
        await JsonTestModel.objects.create(
            name='user1',
            data={'account': 'test_account', 'role': 'admin', 'active': True, 'count': 3},
            count=1
        )
        await JsonTestModel.objects.create(
            name='user2',
            data={'account': 'other_account', 'role': 'user', 'active': False, 'count': 1},
            count=2
        )
        await JsonTestModel.objects.create(
            name='user3',
            data={'role': 'guest', 'active': True, 'count': 2},  # No account key
            count=3
        )
        await JsonTestModel.objects.create(
            name='user4',
            data={'account': 'test_account', 'role': 'user', 'department': 'engineering', 'count': 4},
            count=4
        )

    async def asyncTearDown(self):
        """Clean up PostgreSQL test database."""
        await JsonTestModel.objects.all().delete()


if __name__ == '__main__':
    unittest.main()