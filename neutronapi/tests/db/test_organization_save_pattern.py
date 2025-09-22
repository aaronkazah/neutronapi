"""
Test that models with custom save() methods work properly with the new pk-based logic.
This specifically tests the Organization model pattern.
"""
import unittest
import datetime
import uuid
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, JSONField, DateTimeField
from neutronapi.db.connection import setup_databases, get_databases
from neutronapi.db.migrations import CreateModel


class Organization(Model):
    """Test Organization model with custom save() method."""

    PREFIX = "org"

    id = CharField(primary_key=True, unique=True)
    name = CharField(null=False)
    data = JSONField(null=True, default=dict)
    meta = JSONField(null=True, default=dict)
    created = DateTimeField(null=True)
    modified = DateTimeField(null=True)
    deleted = DateTimeField(null=True)

    async def validate(self):
        """Validates the Organization fields."""
        if not self.name:
            raise Exception("Organization name cannot be empty.")

    async def save(self, *args, **kwargs):
        """Save the organization with automatic field updates."""
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        new_object = not self.id

        if new_object:
            # Generate ID with org_ prefix
            self.id = f"{self.PREFIX}_{uuid.uuid4().hex[:20]}"
            self.created = now

        self.modified = now
        await self.validate()
        # This should now work without create=True!
        await super().save(*args, **kwargs)


class TestOrganizationSavePattern(unittest.IsolatedAsyncioTestCase):
    """Test Organization model with custom save method and pk logic."""

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
        op = CreateModel('neutronapi.Organization', Organization._neutronapi_fields_)
        await op.database_forwards('neutronapi', self.connection.provider, None, None, self.connection)

    async def test_organization_save_without_create_flag(self):
        """Test that Organization.save() works without create=True."""

        # This mimics the exact user code that was failing
        payload = {"name": "Test Org", "data": {"key": "value"}, "meta": {"type": "test"}}
        instance = Organization(
            name=payload.get("name"),
            data=payload.get("data", {}),
            meta=payload.get("meta", {}),
        )

        # Before save: pk should be None, id should be None
        self.assertIsNone(instance.pk)
        self.assertIsNone(getattr(instance, 'id', None))

        # This should work WITHOUT create=True now!
        await instance.save()

        # After save: both pk and id should be set to the same value
        self.assertIsNotNone(instance.pk)
        self.assertIsNotNone(instance.id)
        self.assertEqual(instance.pk, instance.id)
        self.assertTrue(instance.id.startswith("org_"))

    async def test_organization_subsequent_save_updates(self):
        """Test that subsequent saves on Organization do UPDATE, not INSERT."""

        # Create and save organization
        instance = Organization(name="Test Org", data={"key": "value"})
        await instance.save()

        # Verify one record exists
        all_orgs = await Organization.objects.all()
        self.assertEqual(len(list(all_orgs)), 1)

        original_id = instance.id
        original_pk = instance.pk

        # Modify and save again
        instance.name = "Updated Org"
        await instance.save()  # Should UPDATE, not INSERT

        # Should still have exactly one record
        all_orgs_after = await Organization.objects.all()
        self.assertEqual(len(list(all_orgs_after)), 1)

        # IDs should not change
        self.assertEqual(instance.id, original_id)
        self.assertEqual(instance.pk, original_pk)

    async def test_multiple_organizations_get_unique_ids(self):
        """Test that multiple Organization instances get unique IDs."""

        org1 = Organization(name="Org 1")
        org2 = Organization(name="Org 2")
        org3 = Organization(name="Org 3")

        await org1.save()
        await org2.save()
        await org3.save()

        # All should have different IDs
        ids = [org1.id, org2.id, org3.id]
        self.assertEqual(len(set(ids)), 3, "All organizations should have unique IDs")

        # All should have pk set
        self.assertIsNotNone(org1.pk)
        self.assertIsNotNone(org2.pk)
        self.assertIsNotNone(org3.pk)

        # Database should have 3 records
        all_orgs = await Organization.objects.all()
        self.assertEqual(len(list(all_orgs)), 3)


if __name__ == '__main__':
    unittest.main()