import unittest
import os
import tempfile
from neutronapi.db import Model
from neutronapi.db.fields import CharField, JSONField
from neutronapi.db.connection import setup_databases
from neutronapi.db.queryset import Q


class TestObject(Model):
    """Test model for QuerySet testing."""
    key = CharField(null=False)
    name = CharField(null=True)
    kind = CharField(null=True)
    folder = CharField(null=True)  
    parent = CharField(null=True)
    meta = JSONField(null=True, default=dict)
    store = JSONField(null=True, default=dict)
    connections = JSONField(null=True, default=dict)


class TestQuerySetSQLite(unittest.IsolatedAsyncioTestCase):
    def _should_skip_for_provider(self):
        """Skip SQLite-specific tests when running with non-SQLite providers"""
        provider = os.environ.get('DATABASE_PROVIDER', '').lower()
        if provider in ('asyncpg', 'postgres', 'postgresql'):
            self.skipTest('SQLite-specific test skipped when running with PostgreSQL provider')
    
    async def asyncSetUp(self):
        self._should_skip_for_provider()
        
        # Create temporary SQLite database for testing
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        
        # Setup database configuration
        db_config = {
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': self.temp_db.name,
            }
        }
        self.db_manager = setup_databases(db_config)
        
        # Create the table using migration system
        from neutronapi.db.migrations import CreateModel
        connection = await self.db_manager.get_connection()
        
        # Create table for TestObject model using migrations
        create_operation = CreateModel('neutronapi.TestObject', TestObject._neutronapi_fields_)
        await create_operation.database_forwards(
            app_label='neutronapi',
            provider=connection.provider, 
            from_state=None,
            to_state=None,
            connection=connection
        )

    async def asyncTearDown(self):
        """Clean up after each test."""
        await self.db_manager.close_all()
        # Remove temp database file
        try:
            os.unlink(self.temp_db.name)
        except:
            pass

    async def test_crud_and_filters(self):
        # CREATE: Insert test data using Model.objects.create()
        await TestObject.objects.create(
            id="obj-1",
            key="/org-1/files/a.txt", 
            name="A",
            kind="file",
            meta={"tag": "alpha"},
            folder="/org-1/files",
            parent="/org-1"
        )
        await TestObject.objects.create(
            id="obj-2",
            key="/org-1/files/b.txt",
            name="B", 
            kind="file",
            meta={"tag": "beta"},
            folder="/org-1/files",
            parent="/org-1"
        )

        # Test QuerySet operations using Model.objects
        # Count
        count = await TestObject.objects.count()
        self.assertEqual(count, 2)

        # Filter by folder
        folder = '/org-1/files'
        qs_folder = await TestObject.objects.filter(folder=folder)
        results = list(qs_folder)
        self.assertEqual(len(results), 2)

        # Test basic filtering
        qs_alpha = await TestObject.objects.filter(name='A')
        alpha_results = list(qs_alpha)
        self.assertEqual(len(alpha_results), 1)
        self.assertEqual(alpha_results[0].name, 'A')

        # Test first()
        first_result = await TestObject.objects.filter(folder='/org-1/files').first()
        self.assertIsNotNone(first_result)
        self.assertIn(first_result.name, ['A', 'B'])
