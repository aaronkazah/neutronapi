"""
Test cases for using _fields as a field name.

This tests the fix for the bug where _fields couldn't be used as a field name
because it conflicted with internal model metadata storage.
"""

import unittest
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, JSONField, IntegerField
from neutronapi.db.connection import setup_databases, get_databases
from neutronapi.db.migrations import CreateModel


class ModelWithFieldsField(Model):
    """Test model that uses _fields as a field name."""
    
    name = CharField(max_length=100)
    _fields = JSONField(default=dict)
    count = IntegerField(default=0)


class TestFieldsAsFieldName(unittest.IsolatedAsyncioTestCase):
    """Test that _fields can be used as a regular field name."""

    async def asyncSetUp(self):
        """Set up test database and table."""
        # Setup in-memory SQLite database
        setup_databases({
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': ':memory:',
            }
        })
        
        self.connection = await get_databases().get_connection('default')
        
        # Create table using migration
        op = CreateModel('neutronapi.ModelWithFieldsField', ModelWithFieldsField._neutronapi_fields_)
        await op.database_forwards('neutronapi', self.connection.provider, None, None, self.connection)

    async def test_model_creation_with_fields_field(self):
        """Test that a model with _fields field can be created."""
        # Verify the model has _fields as a user field
        self.assertIn('_fields', ModelWithFieldsField._neutronapi_fields_)
        self.assertIn('name', ModelWithFieldsField._neutronapi_fields_)
        self.assertIn('count', ModelWithFieldsField._neutronapi_fields_)
        
        # Verify _fields is treated as a regular field
        fields_field = ModelWithFieldsField._neutronapi_fields_['_fields']
        self.assertEqual(fields_field.__class__.__name__, 'JSONField')

    async def test_instance_creation_and_save(self):
        """Test creating and saving an instance with _fields data."""
        # Create instance with _fields data
        instance = ModelWithFieldsField(
            name='Test Model',
            _fields={'custom': 'data', 'nested': {'key': 'value'}},
            count=42
        )
        
        # Save to database
        await instance.save()
        self.assertIsNotNone(instance.id)
        
        # Verify _fields data is correct
        self.assertEqual(instance._fields, {'custom': 'data', 'nested': {'key': 'value'}})
        self.assertEqual(instance.name, 'Test Model')
        self.assertEqual(instance.count, 42)

    async def test_instance_retrieval(self):
        """Test retrieving instance with _fields data from database."""
        # Create and save instance
        original = ModelWithFieldsField(
            name='Retrieve Test',
            _fields={'test': 'data', 'numbers': [1, 2, 3]},
            count=100
        )
        await original.save()
        
        # Retrieve from database
        retrieved = await ModelWithFieldsField.objects.get(id=original.id)
        
        # Verify all fields including _fields
        self.assertEqual(retrieved.name, 'Retrieve Test')
        self.assertEqual(retrieved._fields, {'test': 'data', 'numbers': [1, 2, 3]})
        self.assertEqual(retrieved.count, 100)
        self.assertEqual(retrieved.id, original.id)

    async def test_instance_update(self):
        """Test updating instance with _fields modifications."""
        # Create and save instance
        instance = ModelWithFieldsField(
            name='Update Test',
            _fields={'original': 'data'},
            count=1
        )
        await instance.save()
        original_id = instance.id
        
        # Update _fields and other fields
        instance.name = 'Updated Name'
        instance._fields = {'updated': 'data', 'new_key': 'new_value'}
        instance.count = 2
        await instance.save()
        
        # Verify updates were saved
        self.assertEqual(instance.id, original_id)  # ID shouldn't change
        
        # Retrieve fresh copy to verify database update
        updated = await ModelWithFieldsField.objects.get(id=original_id)
        self.assertEqual(updated.name, 'Updated Name')
        self.assertEqual(updated._fields, {'updated': 'data', 'new_key': 'new_value'})
        self.assertEqual(updated.count, 2)

    async def test_query_by_other_fields(self):
        """Test querying by non-_fields attributes works correctly."""
        # Create test instances
        await ModelWithFieldsField.objects.create(
            name='Query Test 1',
            _fields={'type': 'first'},
            count=10
        )
        await ModelWithFieldsField.objects.create(
            name='Query Test 2', 
            _fields={'type': 'second'},
            count=20
        )
        
        # Query by name
        result_qs = await ModelWithFieldsField.objects.filter(name='Query Test 1')
        result_list = list(result_qs)
        self.assertEqual(len(result_list), 1)
        self.assertEqual(result_list[0]._fields, {'type': 'first'})
        
        # Query by count
        result_qs = await ModelWithFieldsField.objects.filter(count=20)
        result_list = list(result_qs)
        self.assertEqual(len(result_list), 1)
        self.assertEqual(result_list[0].name, 'Query Test 2')

    async def test_multiple_instances_with_different_fields_data(self):
        """Test multiple instances with different _fields data."""
        instances_data = [
            {'name': 'Instance 1', '_fields': {'role': 'admin', 'permissions': ['read', 'write']}, 'count': 1},
            {'name': 'Instance 2', '_fields': {'role': 'user', 'settings': {'theme': 'dark'}}, 'count': 2},
            {'name': 'Instance 3', '_fields': {}, 'count': 3},  # Empty _fields
        ]
        
        created_instances = []
        for data in instances_data:
            instance = await ModelWithFieldsField.objects.create(**data)
            created_instances.append(instance)
        
        # Verify all instances were created correctly
        all_instances = await ModelWithFieldsField.objects.all()
        self.assertEqual(len(all_instances), 3)
        
        # Verify each instance has correct data
        for i, instance in enumerate(created_instances):
            self.assertEqual(instance.name, instances_data[i]['name'])
            self.assertEqual(instance._fields, instances_data[i]['_fields'])
            self.assertEqual(instance.count, instances_data[i]['count'])

    async def test_internal_metadata_separation(self):
        """Test that internal metadata is properly separated from user _fields."""
        # Verify internal metadata uses _neutronapi_fields_
        self.assertTrue(hasattr(ModelWithFieldsField, '_neutronapi_fields_'))
        self.assertIsInstance(ModelWithFieldsField._neutronapi_fields_, dict)

        # Verify _fields is treated as a user field in the metadata
        self.assertIn('_fields', ModelWithFieldsField._neutronapi_fields_)

        # Create instance and verify it doesn't interfere with internal metadata
        instance = ModelWithFieldsField(
            name='Metadata Test',
            _fields={'this': 'should not interfere', 'with': 'internal metadata'}
        )

        # Verify instance still has access to model metadata through internal attribute
        self.assertIn('name', instance._neutronapi_fields_)
        self.assertIn('_fields', instance._neutronapi_fields_)
        self.assertIn('count', instance._neutronapi_fields_)

    async def test_json_field_key_filtering_fails(self):
        """Test that JSON field key filtering (_fields__account) fails as expected."""
        # Create test data with JSON field containing 'account' key
        await ModelWithFieldsField.objects.create(
            name='user_with_account',
            _fields={'account': 'test_account', 'role': 'admin'},
            count=1
        )
        await ModelWithFieldsField.objects.create(
            name='user_without_account',
            _fields={'role': 'user'},
            count=2
        )

        # Test that direct JSON key filtering fails
        # This demonstrates why we need manual filtering fallback
        with self.assertRaises(Exception) as context:
            await ModelWithFieldsField.objects.filter(_fields__account='test_account')

        # Should get "Unsupported lookup type: account"
        self.assertIn("Unsupported lookup type", str(context.exception))

        # Demonstrate that exact JSON matching works
        results = await ModelWithFieldsField.objects.filter(
            _fields={'account': 'test_account', 'role': 'admin'}
        )
        results_list = list(results)
        self.assertEqual(len(results_list), 1)
        self.assertEqual(results_list[0].name, 'user_with_account')

        # Show manual filtering works (what our fallback does)
        all_records = await ModelWithFieldsField.objects.all()
        matching_records = [
            record for record in all_records
            if isinstance(record._fields, dict) and record._fields.get('account') == 'test_account'
        ]
        self.assertEqual(len(matching_records), 1)
        self.assertEqual(matching_records[0].name, 'user_with_account')


if __name__ == '__main__':
    unittest.main()