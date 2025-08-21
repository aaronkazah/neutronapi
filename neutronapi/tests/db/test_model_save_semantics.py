import os
import unittest

from neutronapi.db import setup_databases, get_databases
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, DateTimeField


class UniqueEmailModel(Model):
    """Model used to validate save semantics: create vs update.

    Expectations:
    - On initial creation, a single row is inserted and `id` is populated.
    - Subsequent `save()` on the same instance updates the existing row rather than inserting a new one.
    - Unique constraints (e.g., on `email`) must not be violated by repeat saves.
    """

    # Default PK is a CharField; library auto-generates time-sortable ID on create
    id = CharField(primary_key=True, unique=True)
    email = CharField(null=False, unique=True)
    name = CharField(null=True)
    created = DateTimeField(null=True)
    modified = DateTimeField(null=True)


class TestModelSaveSemantics(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Force an in-memory SQLite DB for deterministic tests
        os.environ['TESTING'] = '1'
        cfg = {
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': ':memory:',
            }
        }
        setup_databases(cfg)
        conn = await get_databases().get_connection('default')
        self.provider = conn.provider

        # Create backing table with unique constraint on email
        app_label, table_base = UniqueEmailModel._get_parsed_table_name()
        await self.provider.create_table(app_label, table_base, list(UniqueEmailModel._fields.items()))

    async def asyncTearDown(self):
        try:
            app_label, table_base = UniqueEmailModel._get_parsed_table_name()
            await self.provider.drop_table(app_label, table_base)
        except Exception:
            pass

    async def test_id_populated_on_create(self):
        obj = await UniqueEmailModel.objects.create(email="unique@example.com", name="Alpha")
        self.assertIsInstance(obj.id, str)
        self.assertTrue(len(obj.id) > 0)

    async def test_save_updates_instead_of_inserting(self):
        # Create one row
        obj = await UniqueEmailModel.objects.create(email="dup@example.com", name="First")

        # Sanity: one row exists
        self.assertEqual(await UniqueEmailModel.objects.count(), 1)

        # Modify a non-unique field and save; should update existing row, not insert a new one
        obj.name = "Updated"
        await obj.save()  # Expected behavior: UPDATE existing row, not INSERT

        # Still one row; unique(email) not violated
        self.assertEqual(await UniqueEmailModel.objects.count(), 1)

        # Confirm persisted change by reloading from DB
        reloaded = await UniqueEmailModel.objects.filter(id=obj.id).first()
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.name, "Updated")

    async def test_save_with_create_false_is_update(self):
        obj = await UniqueEmailModel.objects.create(email="flag@example.com", name="First")
        self.assertEqual(await UniqueEmailModel.objects.count(), 1)

        obj.name = "Second"
        # Explicitly request update path; should never insert
        await obj.save(create=False)
        self.assertEqual(await UniqueEmailModel.objects.count(), 1)
        reloaded = await UniqueEmailModel.objects.filter(id=obj.id).first()
        self.assertEqual(reloaded.name, "Second")

