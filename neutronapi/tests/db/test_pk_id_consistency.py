"""
Test that pk and id work together properly for insert/update detection.
This test should FAIL until we fix the pk property to return the correct value.
"""
import unittest
import datetime
import uuid
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, JSONField, DateTimeField
from neutronapi.db.connection import setup_databases, get_databases
from neutronapi.db.migrations import CreateModel


class OrganizationWithCustomSave(Model):
    """Model that mimics the real Organization pattern that's failing."""

    PREFIX = "org"

    id = CharField(primary_key=True, unique=True)
    name = CharField(null=False)
    data = JSONField(null=True, default=dict)
    created = DateTimeField(null=True)
    modified = DateTimeField(null=True)

    async def save(self, *args, **kwargs):
        """Custom save method that sets ID before calling super()."""
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        new_object = not self.id

        if new_object:
            # Generate ID with prefix (like real Organization model)
            self.id = f"{self.PREFIX}_{uuid.uuid4().hex[:20]}"
            self.created = now

        self.modified = now
        # This should work without create=True, but will fail if pk != id
        await super().save(*args, **kwargs)


class TestPKIDConsistency(unittest.IsolatedAsyncioTestCase):
    """Test that pk and id are consistent for proper insert/update detection."""

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
        op = CreateModel('neutronapi.OrganizationWithCustomSave', OrganizationWithCustomSave._neutronapi_fields_)
        await op.database_forwards('neutronapi', self.connection.provider, None, None, self.connection)

    async def test_fresh_instance_creates_correctly(self):
        """Test that fresh instances work with pk logic."""
        org = OrganizationWithCustomSave(name="Test Org")

        # Fresh object should have pk = None
        self.assertIsNone(org.pk)
        self.assertIsNone(org.id)

        await org.save()

        # After save: should have ID and pk set
        self.assertIsNotNone(org.id)
        self.assertIsNotNone(org.pk)
        self.assertEqual(org.pk, org.id)
        self.assertTrue(org.id.startswith("org_"))

    async def test_manual_id_assignment_still_creates(self):
        """Test that manually setting ID still creates (not updates)."""
        org = OrganizationWithCustomSave(name="Test Org")

        # Manually set ID (like Organization model does)
        org.id = "org_manual_test_id"

        # Should still be pk = None (fresh object)
        self.assertIsNone(org.pk)

        # Should INSERT, not UPDATE
        await org.save()

        # After save: pk should be set
        self.assertEqual(org.pk, org.id)

        # Verify it was saved
        all_orgs = await OrganizationWithCustomSave.objects.all()
        count = len(list(all_orgs))
        self.assertEqual(count, 1)

    async def test_update_works_with_existing_id(self):
        """Test that updates work when object has existing ID (the failing case!)."""

        # Create an organization
        org = OrganizationWithCustomSave(name="Original Name")
        await org.save()

        original_id = org.id
        self.assertEqual(org.pk, org.id, "After save, pk should equal id")

        # Now update the organization (this is where it fails!)
        org.name = "Updated Name"

        # This should do UPDATE, not INSERT
        await org.save()

        # After update: should have same ID, no duplicates created
        self.assertEqual(org.id, original_id, "ID should not change on update")

        # Verify only one record exists (no duplicate INSERT)
        all_orgs = await OrganizationWithCustomSave.objects.all()
        count = len(list(all_orgs))
        self.assertEqual(count, 1, f"Should have exactly 1 organization, found {count}")

    async def test_loaded_object_updates_correctly(self):
        """Test that objects loaded from DB can be updated."""

        # Create and save
        org = OrganizationWithCustomSave(name="DB Test")
        await org.save()
        org_id = org.id

        # Load from database
        loaded_org = await OrganizationWithCustomSave.objects.filter(id=org_id).first()

        # Loaded object should have pk = id
        self.assertIsNotNone(loaded_org)
        self.assertEqual(loaded_org.pk, loaded_org.id, "Loaded object should have pk = id")

        # Update loaded object (this often fails)
        loaded_org.name = "Updated from DB"
        await loaded_org.save()  # Should UPDATE, not INSERT

        # Verify still only one record
        all_orgs = await OrganizationWithCustomSave.objects.all()
        count = len(list(all_orgs))
        self.assertEqual(count, 1, f"After updating loaded object, should have 1 org, found {count}")

    async def test_fresh_instance_with_existing_id_upserts_correctly(self):
        """Test that fresh instance with existing ID does UPSERT (update existing record)."""

        # Create and save first organization
        org1 = OrganizationWithCustomSave(name="First Org")
        await org1.save()
        existing_id = org1.id

        # Create second organization with same ID (manually set)
        org2 = OrganizationWithCustomSave(name="Second Org")
        org2.id = existing_id  # Set to existing ID

        # org2 should still have pk = None (fresh object)
        self.assertIsNone(org2.pk)

        # This should UPSERT (update the existing record instead of failing)
        await org2.save()

        # After save: pk should be set
        self.assertEqual(org2.pk, org2.id)

        # Should still have only 1 record (updated, not inserted)
        all_orgs = await OrganizationWithCustomSave.objects.all()
        count = len(list(all_orgs))
        self.assertEqual(count, 1, f"Should have exactly 1 organization after UPSERT, found {count}")

        # The record should have the new name (from org2)
        updated_org = await OrganizationWithCustomSave.objects.filter(id=existing_id).first()
        self.assertEqual(updated_org.name, "Second Org", "Should have updated name from org2")


if __name__ == '__main__':
    unittest.main()