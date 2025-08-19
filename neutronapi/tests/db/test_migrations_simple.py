import os
import tempfile
import textwrap
import shutil
import unittest
import os
import datetime
import logging
from unittest import IsolatedAsyncioTestCase

from neutronapi.db.migrations import (
    MigrationManager,
    Migration,
    CreateModel,
    AddField,
    RemoveField,
    RenameField,
    RenameModel,
    AlterField,
    DeleteModel,
)
from neutronapi.db.fields import CharField, IntegerField, DateTimeField, BooleanField
from neutronapi.db.models import Model
from neutronapi.db.connection import get_databases, DatabaseType
from neutronapi.tests.db.test_utils import table_exists, get_columns_dict


class TestBasicMigrationOperations(IsolatedAsyncioTestCase):
    """Test basic migration operations with SQLite provider directly."""
    
    def setUp(self):
        self.app_label = "test_app"
        
    async def asyncSetUp(self):
        conn = await get_databases().get_connection('default')
        self.provider = conn.provider
        
    async def asyncTearDown(self):
        pass
        
    def _get_table_name(self, model_name):
        """Convert ModelName to app_label_modelname format."""
        snake_case = "".join(
            ["_" + c.lower() if c.isupper() else c.lower() for c in model_name]
        ).lstrip("_")
        return f"{self.app_label}_{snake_case}"
        
    async def _table_exists(self, table_name):
        """Check if table exists (provider-aware)."""
        conn = await get_databases().get_connection('default')
        return await table_exists(conn, self.provider, self.app_label, table_name)
        
    async def _get_table_columns(self, table_name):
        """Get table column information (provider-aware)."""
        conn = await get_databases().get_connection('default')
        return await get_columns_dict(conn, self.provider, self.app_label, table_name)
        
    async def test_create_model_basic(self):
        """Test basic model creation."""
        model_name = f"{self.app_label}.TestModel"
        fields = {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
            "created_at": DateTimeField(default=datetime.datetime.now),
        }
        
        operation = CreateModel(model_name, fields)
        await operation.database_forwards(
            self.app_label, self.provider, None, None, None
        )
        
        table_name = self._get_table_name("TestModel")
        self.assertTrue(await self._table_exists(table_name))
        
        columns = await self._get_table_columns(table_name)
        self.assertIn("id", columns)
        self.assertIn("name", columns) 
        self.assertIn("created_at", columns)
        
    async def test_add_field_to_existing_table(self):
        """Test adding a field to existing table."""
        model_name = f"{self.app_label}.User"
        
        # Create base table first
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, None
        )
        
        # Add a field (make it nullable to avoid SQLite constraint issues)
        add_op = AddField(model_name, "email", CharField(max_length=200, null=True))
        await add_op.database_forwards(
            self.app_label, self.provider, None, None, None
        )
        
        table_name = self._get_table_name("User")
        columns = await self._get_table_columns(table_name)
        self.assertIn("email", columns)
        
    async def test_rename_field(self):
        """Test renaming a field."""
        model_name = f"{self.app_label}.Article"
        
        # Create table
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "title": CharField(max_length=200),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, None
        )
        
        # Rename field
        rename_op = RenameField(model_name, "title", "headline")
        await rename_op.database_forwards(
            self.app_label, self.provider, None, None, None
        )
        
        table_name = self._get_table_name("Article")
        columns = await self._get_table_columns(table_name)
        self.assertNotIn("title", columns)
        self.assertIn("headline", columns)
        
    async def test_remove_field(self):
        """Test removing a field."""
        model_name = f"{self.app_label}.Product"
        
        # Create table
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
            "price": IntegerField(),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, None
        )
        
        # Remove field
        remove_op = RemoveField(model_name, "price")
        await remove_op.database_forwards(
            self.app_label, self.provider, None, None, None
        )
        
        table_name = self._get_table_name("Product")
        columns = await self._get_table_columns(table_name)
        self.assertNotIn("price", columns)
        self.assertIn("name", columns)  # Other columns should remain
        
    async def test_rename_table(self):
        """Test renaming a table."""
        old_model = f"{self.app_label}.OldModel"
        new_model = f"{self.app_label}.NewModel"
        
        # Create table
        create_op = CreateModel(old_model, {
            "id": CharField(primary_key=True),
            "data": CharField(max_length=100),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, None
        )
        
        # Rename table
        rename_op = RenameModel(old_model, new_model)
        await rename_op.database_forwards(
            self.app_label, self.provider, None, None, None
        )
        
        old_table = self._get_table_name("OldModel")
        new_table = self._get_table_name("NewModel")
        
        self.assertFalse(await self._table_exists(old_table))
        self.assertTrue(await self._table_exists(new_table))
        
    async def test_complex_migration_sequence(self):
        """Test a sequence of operations in one migration."""
        operations = [
            CreateModel(f"{self.app_label}.Blog", {
                "id": CharField(primary_key=True),
                "title": CharField(max_length=200),
            }),
            AddField(f"{self.app_label}.Blog", "content", CharField(max_length=1000, null=True)),
            RenameField(f"{self.app_label}.Blog", "title", "headline"),
            AddField(f"{self.app_label}.Blog", "published", BooleanField(default=False)),
        ]
        
        migration = Migration(self.app_label, operations)
        await migration.apply({}, self.provider, None)
        
        # Verify final state
        table_name = self._get_table_name("Blog")
        columns = await self._get_table_columns(table_name)
        
        self.assertIn("headline", columns)  # renamed from title
        self.assertIn("content", columns)   # added field
        self.assertIn("published", columns) # added field
        self.assertNotIn("title", columns)  # should be renamed


class TestMigrationManagerBasic(IsolatedAsyncioTestCase):
    """Test basic migration manager functionality."""
    
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.apps_dir = os.path.join(self.temp_dir, 'apps')
        os.makedirs(self.apps_dir, exist_ok=True)
        
        # Create test app structure
        self.app_label = 'testapp'
        self.app_dir = os.path.join(self.apps_dir, self.app_label)
        models_dir = os.path.join(self.app_dir, 'models')
        migrations_dir = os.path.join(self.app_dir, 'migrations')
        
        for dir_path in [self.app_dir, models_dir, migrations_dir]:
            os.makedirs(dir_path, exist_ok=True)
            with open(os.path.join(dir_path, '__init__.py'), 'w') as f:
                f.write("")
        
        # Write test model
        with open(os.path.join(models_dir, 'test_model.py'), 'w') as f:
            f.write(textwrap.dedent("""
                from neutronapi.db.models import Model
                from neutronapi.db.fields import CharField, IntegerField
                
                class TestModel(Model):
                    name = CharField(max_length=100)
                    value = IntegerField(null=True)
                    
                    @classmethod
                    def get_app_label(cls):
                        return 'testapp'
            """))
            
        self.manager = MigrationManager(apps=[self.app_label], base_dir=self.apps_dir)
        conn = await get_databases().get_connection('default')
        self.provider = conn.provider
        
    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir)
        
    async def test_model_discovery(self):
        """Test that models are discovered correctly."""
        models = self.manager._discover_models(self.app_label)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].__name__, "TestModel")
        
    async def test_makemigrations_clean_mode(self):
        """Test migration generation in clean mode."""
        models = self.manager._discover_models(self.app_label)
        operations = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=True  # Don't use previous state
        )
        
        self.assertTrue(operations)
        self.assertEqual(len(operations), 1)
        self.assertIsInstance(operations[0], CreateModel)
        self.assertEqual(operations[0].model_name, f"{self.app_label}.TestModel")
        
    async def test_apply_operations_directly(self):
        """Test applying operations directly via manager."""
        models = self.manager._discover_models(self.app_label)
        operations = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=True
        )
        
        # Verify operations were generated
        self.assertTrue(operations, "No operations generated")
        self.assertEqual(len(operations), 1, "Should have exactly 1 operation")
        
        # Apply operations directly
        await self.manager.migrate(self.app_label, self.provider, operations=operations)
        
        # List tables provider-aware
        conn = await get_databases().get_connection('default')
        is_pg = getattr(conn, 'db_type', None) == DatabaseType.POSTGRES
        if is_pg:
            rows = await self.provider.fetchall(
                "SELECT table_name AS name FROM information_schema.tables WHERE table_schema=$1",
                (self.app_label,)
            )
            table_names = [r['name'] for r in rows]
            expected_table_name = "test_model"  # Base name under app schema
        else:
            all_tables = await self.provider.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            table_names = [table['name'] for table in all_tables]
            expected_table_name = f"{self.app_label}_test_model"

        self.assertIn(expected_table_name, table_names,
                       f"Table {expected_table_name} should exist in {table_names}")


class TestErrorHandling(IsolatedAsyncioTestCase):
    """Test error handling in migrations."""
    
    async def asyncSetUp(self):
        self.app_label = "error_test"
        conn = await get_databases().get_connection('default')
        self.connection = conn
        self.provider = conn.provider
        
    async def asyncTearDown(self):
        pass
        
    async def test_add_field_to_nonexistent_table(self):
        """Test adding field to non-existent table."""
        model_name = f"{self.app_label}.NonExistent"
        add_op = AddField(model_name, "test_field", CharField(max_length=100))
        
        with self.assertRaises(Exception):
            await add_op.database_forwards(
                self.app_label, self.provider, None, None, None
            )
            
    async def test_create_duplicate_table(self):
        """Test creating table that already exists (should be idempotent)."""
        model_name = f"{self.app_label}.DuplicateTest"
        fields = {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
        }
        
        # Create table first time
        create_op1 = CreateModel(model_name, fields)
        await create_op1.database_forwards(
            self.app_label, self.provider, None, None, None
        )
        
        # Verify table exists (DuplicateTest -> duplicate_test in snake_case)
        table_name = f"{self.app_label}_duplicate_test" 
        from neutronapi.tests.db.test_utils import table_exists
        exists1 = await table_exists(self.connection, self.provider, self.app_label, table_name)
        self.assertTrue(exists1, "First table creation should succeed")
        
        # Try to create same table again - should be idempotent (no error)
        create_op2 = CreateModel(model_name, fields)
        try:
            await create_op2.database_forwards(
                self.app_label, self.provider, None, None, None
            )
            # Should not raise an error - this is idempotent behavior
        except Exception as e:
            self.fail(f"Duplicate table creation should be idempotent, but got error: {e}")
            
        # Verify table still exists
        exists2 = await table_exists(self.connection, self.provider, self.app_label, table_name)
        self.assertTrue(exists2, "Table should still exist after duplicate creation attempt")
