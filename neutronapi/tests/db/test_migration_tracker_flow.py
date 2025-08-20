import os
import shutil
import tempfile
import unittest
import hashlib

from unittest import IsolatedAsyncioTestCase

from neutronapi.db.migrations import MigrationManager
from neutronapi.db.migration_tracker import MigrationTracker
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, IntegerField
from neutronapi.db.connection import get_databases


class TestMigrationTrackerFlow(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Use a temp apps directory for migrations
        self.base_dir = tempfile.mkdtemp(prefix="neutronapi_migflow_")
        # Ensure DB is available (default sqlite)
        self.databases = get_databases()
        self.connection = await self.databases.get_connection('default')

    async def asyncTearDown(self):
        try:
            await self.databases.close_all()
        finally:
            shutil.rmtree(self.base_dir, ignore_errors=True)

    def _migrations_path(self, app_label: str):
        return os.path.join(self.base_dir, app_label, 'migrations')

    async def test_numbering_idempotency_hash_and_field_changes(self):
        app_label = 'alpha'
        manager = MigrationManager(base_dir=self.base_dir)

        # Define initial model
        class User(Model):
            name = CharField(max_length=100)

            @classmethod
            def get_app_label(cls):
                return app_label

        # 1) First makemigrations → 0001_*.py
        ops = await manager.makemigrations(app_label, models=[User], return_ops=False, clean=False)
        self.assertIsNotNone(ops)
        mig_dir = self._migrations_path(app_label)
        files = sorted([f for f in os.listdir(mig_dir) if f.endswith('.py') and f != '__init__.py'])
        self.assertEqual(files[0][:4], '0001', 'First migration should start with 0001_ prefix')
        first_file = os.path.join(mig_dir, files[0])

        # 2) Running again with no changes → no new file
        ops = await manager.makemigrations(app_label, models=[User], return_ops=False, clean=False)
        self.assertIsNone(ops)
        files_after = sorted([f for f in os.listdir(mig_dir) if f.endswith('.py') and f != '__init__.py'])
        self.assertEqual(files_after, files, 'No new migration file should be created when no field changes')

        # 3) Add a field and run makemigrations → 0002_*.py
        class User(Model):
            name = CharField(max_length=100)
            age = IntegerField(default=0)

            @classmethod
            def get_app_label(cls):
                return app_label

        ops = await manager.makemigrations(app_label, models=[User], return_ops=False, clean=False)
        self.assertIsNotNone(ops)
        files_v2 = sorted([f for f in os.listdir(mig_dir) if f.endswith('.py') and f != '__init__.py'])
        self.assertEqual(len(files_v2), 2)
        self.assertTrue(any(f.startswith('0002') for f in files_v2), 'Second migration should start with 0002_ prefix')
        second_file = os.path.join(mig_dir, [f for f in files_v2 if f.startswith('0002')][0])

        # 4) Makemigrations again with same fields → still only two files
        ops = await manager.makemigrations(app_label, models=[User], return_ops=False, clean=False)
        self.assertIsNone(ops)
        files_v2_again = sorted([f for f in os.listdir(mig_dir) if f.endswith('.py') and f != '__init__.py'])
        self.assertEqual(files_v2_again, files_v2, 'Should not create new files on repeated runs without changes')

        # 5) Apply migrations using MigrationTracker
        tracker = MigrationTracker(base_dir=self.base_dir)
        await tracker.migrate(self.connection)

        # Verify record hash for 0002 is stored
        def file_hash(path: str) -> str:
            with open(path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()

        before_hash = file_hash(second_file)
        record = await tracker.get_migration_record(self.connection, app_label, os.path.splitext(os.path.basename(second_file))[0])
        self.assertIsNotNone(record, 'Migration record should be stored after migrate')
        self.assertEqual(record.file_hash, before_hash)

        # 6) Modify 0002 file content (simulate manual edit) and run migrate again → re-applied, hash updated
        with open(second_file, 'a') as f:
            f.write('\n# tweak to change hash')
        after_hash = file_hash(second_file)
        self.assertNotEqual(before_hash, after_hash, 'File hash should change after edit')

        await tracker.migrate(self.connection)

        record2 = await tracker.get_migration_record(self.connection, app_label, os.path.splitext(os.path.basename(second_file))[0])
        self.assertIsNotNone(record2)
        self.assertEqual(record2.file_hash, after_hash, 'Tracker should update stored hash after re-apply')

        # 7) Ensure editing a migration file does NOT cause makemigrations to create a new file (only field changes matter)
        ops = await manager.makemigrations(app_label, models=[User], return_ops=False, clean=False)
        self.assertIsNone(ops)
        files_after_edit = sorted([f for f in os.listdir(mig_dir) if f.endswith('.py') and f != '__init__.py'])
        self.assertEqual(files_after_edit, files_v2, 'Editing migration file should not produce a new migration when fields unchanged')

        # 8) Change field definition (trigger AlterField) → create 0003_*.py
        class User(Model):
            name = CharField(max_length=120)  # Altered from 100 to 120
            age = IntegerField(default=0)

            @classmethod
            def get_app_label(cls):
                return app_label

        ops = await manager.makemigrations(app_label, models=[User], return_ops=False, clean=False)
        self.assertIsNotNone(ops)
        files_v3 = sorted([f for f in os.listdir(mig_dir) if f.endswith('.py') and f != '__init__.py'])
        self.assertEqual(len(files_v3), 3)
        self.assertTrue(any(f.startswith('0003') for f in files_v3), 'Third migration should start with 0003_ prefix')

        # 9) Re-run makemigrations without changes → still only three files
        ops = await manager.makemigrations(app_label, models=[User], return_ops=False, clean=False)
        self.assertIsNone(ops)
        files_v3_again = sorted([f for f in os.listdir(mig_dir) if f.endswith('.py') and f != '__init__.py'])
        self.assertEqual(files_v3_again, files_v3, 'No new migration on repeated run without field changes')
