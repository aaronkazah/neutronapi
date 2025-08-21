import unittest
import os
import tempfile
from neutronapi.db import Model
from neutronapi.db.fields import CharField, JSONField
from neutronapi.db.connection import setup_databases
from neutronapi.db.queryset import QuerySet


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


class TestQuerySetMoreSQLite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
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
        create_operation = CreateModel('neutronapi.TestObject', TestObject._fields)
        await create_operation.database_forwards(
            app_label='neutronapi',
            provider=connection.provider, 
            from_state=None,
            to_state=None,
            connection=connection
        )

        # Seed data with duplicates and JSON numbers using Model.objects.create
        await TestObject.objects.create(
            id="obj-3",
            key="/org-1/files/c.txt",
            name="C",
            kind="file",
            meta={"tag": "alpha", "score": 10},
            folder="/org-1/files",
            parent="/org-1",
        )
        await TestObject.objects.create(
            id="obj-4",
            key="/org-1/files/d.txt",
            name="A",
            kind="file",
            meta={"tag": "alpha", "score": 3},
            folder="/org-1/files",
            parent="/org-1",
        )

    async def asyncTearDown(self):
        await self.db_manager.close_all()
        os.unlink(self.temp_db.name)

    async def test_values_and_exclude(self):
        names = await TestObject.objects.values_list('name', flat=True).all()
        self.assertIn('A', names)
        self.assertIn('C', names)

        excl = await TestObject.objects.exclude(name='A').values_list('name', flat=True).all()
        self.assertNotIn('A', excl)

    async def test_distinct_and_last(self):
        distinct_names = await TestObject.objects.values_list('name', flat=True).distinct('name').all()
        # Both A and C should be present without duplicates
        self.assertCountEqual(distinct_names, ['A', 'C'])

        # last() without explicit order should use -created
        last_obj = await TestObject.objects.last()
        self.assertIsNotNone(last_obj)
        self.assertIn(last_obj.name, ['A', 'C'])

    async def test_json_lookups(self):
        high = await TestObject.objects.filter(meta__score__gt=5).values_list('name', flat=True).all()
        self.assertEqual(high, ['C'])

        alpha = await TestObject.objects.filter(meta__tag__contains='alp').values_list('name', flat=True).all()
        self.assertCountEqual(alpha, ['C', 'A'])
