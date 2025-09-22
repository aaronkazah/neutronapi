"""
Test that save() method works automatically without needing create=True for fresh instances.
This fixes the Django-like behavior where fresh instances should auto-detect they need INSERT.
"""
import unittest
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, JSONField, IntegerField
from neutronapi.db.connection import setup_databases, get_databases
from neutronapi.db.migrations import CreateModel


class AutoSaveTestModel(Model):
    """Test model to verify automatic save behavior."""

    name = CharField(max_length=100)
    data = JSONField(default=dict)
    count = IntegerField(default=0)


class TestAutoSaveWithoutCreateFlag(unittest.IsolatedAsyncioTestCase):
    """Test that save() works automatically like Django without create=True."""

    async def asyncSetUp(self):
        """Set up test database and table."""
        setup_databases({
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': ':memory:',
            }
        })

        self.connection = await get_databases().get_connection('default')

        # Create table
        op = CreateModel('neutronapi.AutoSaveTestModel', AutoSaveTestModel._neutronapi_fields_)
        await op.database_forwards('neutronapi', self.connection.provider, None, None, self.connection)

    async def test_fresh_instance_saves_automatically_without_create_flag(self):
        """Test that fresh instances can save() without needing create=True."""

        # Create fresh instance (like Django style)
        instance = AutoSaveTestModel(
            name="test_user",
            data={"account": "test_account", "role": "admin"},
            count=42
        )

        # Before save, id should be None or empty
        self.assertIn(getattr(instance, 'id', None), [None, ""])

        # This should work automatically without create=True (like Django)
        await instance.save()

        # After save, id should be populated
        self.assertIsNotNone(instance.id)
        self.assertNotEqual(instance.id, "")
        self.assertIsInstance(instance.id, str)

    async def test_fresh_instance_creates_single_record(self):
        """Test that fresh instance creates exactly one record."""

        # Start with empty database
        initial_count = await AutoSaveTestModel.objects.count()
        self.assertEqual(initial_count, 0)

        # Create and save fresh instance
        instance = AutoSaveTestModel(
            name="another_user",
            data={"type": "premium"},
            count=100
        )
        await instance.save()

        # Should have exactly one record
        final_count = await AutoSaveTestModel.objects.count()
        self.assertEqual(final_count, 1)

        # Verify the record contains correct data
        saved_record = await AutoSaveTestModel.objects.first()
        self.assertEqual(saved_record.name, "another_user")
        self.assertEqual(saved_record.data["type"], "premium")
        self.assertEqual(saved_record.count, 100)

    async def test_subsequent_saves_update_not_insert(self):
        """Test that subsequent saves on same instance update, don't insert."""

        # Create and save fresh instance
        instance = AutoSaveTestModel(
            name="update_test",
            data={"status": "active"},
            count=1
        )
        await instance.save()

        # Verify one record exists
        self.assertEqual(await AutoSaveTestModel.objects.count(), 1)
        original_id = instance.id

        # Modify and save again
        instance.name = "updated_name"
        instance.count = 999
        await instance.save()  # Should UPDATE, not INSERT

        # Should still have exactly one record
        self.assertEqual(await AutoSaveTestModel.objects.count(), 1)

        # ID should not change
        self.assertEqual(instance.id, original_id)

        # Verify the changes were persisted
        reloaded = await AutoSaveTestModel.objects.filter(id=instance.id).first()
        self.assertEqual(reloaded.name, "updated_name")
        self.assertEqual(reloaded.count, 999)

    async def test_multiple_fresh_instances_each_get_unique_ids(self):
        """Test that multiple fresh instances each get unique auto-generated IDs."""

        # Create multiple fresh instances
        instance1 = AutoSaveTestModel(name="user1", count=1)
        instance2 = AutoSaveTestModel(name="user2", count=2)
        instance3 = AutoSaveTestModel(name="user3", count=3)

        # Save them all
        await instance1.save()
        await instance2.save()
        await instance3.save()

        # All should have different IDs
        ids = [instance1.id, instance2.id, instance3.id]
        self.assertEqual(len(set(ids)), 3, "All instances should have unique IDs")

        # Database should have 3 records
        self.assertEqual(await AutoSaveTestModel.objects.count(), 3)

    async def test_save_with_explicit_create_true_still_works(self):
        """Test that explicit create=True still works (backward compatibility)."""

        instance = AutoSaveTestModel(
            name="explicit_create",
            data={"test": True},
            count=555
        )

        # Explicit create=True should still work
        await instance.save(create=True)

        self.assertIsNotNone(instance.id)
        saved = await AutoSaveTestModel.objects.filter(id=instance.id).first()
        self.assertEqual(saved.name, "explicit_create")
        self.assertEqual(saved.count, 555)

    async def test_save_with_explicit_create_false_on_fresh_instance_should_fail(self):
        """Test that create=False on fresh instance should fail (no ID to update)."""

        instance = AutoSaveTestModel(name="should_fail", count=0)

        # This should fail because there's no existing record to update
        with self.assertRaises(Exception):
            await instance.save(create=False)


if __name__ == '__main__':
    unittest.main()