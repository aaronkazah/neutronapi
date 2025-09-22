import os
import tempfile
import textwrap
import shutil
import datetime
from unittest import IsolatedAsyncioTestCase
import os

from neutronapi.db.migrations import (
    MigrationManager,
    Migration,
    CreateModel,
    AddField,
    RemoveField,
    RenameField,
    RenameModel,
    DeleteModel,
)
from neutronapi.db.fields import CharField, IntegerField, DateTimeField, BooleanField
from neutronapi.db.connection import get_databases
from neutronapi.tests.db.test_utils import table_exists, get_columns_dict


class TestMigrationOperations(IsolatedAsyncioTestCase):
    """Test individual migration operations thoroughly."""

    def setUp(self):
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        self.app_label = f"test_migrations_{unique_id}"

    async def asyncSetUp(self):
        conn = await get_databases().get_connection('default')
        self.connection = conn
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
        return await table_exists(self.connection, self.provider, self.app_label, table_name)
        
    async def _get_table_columns(self, table_name):
        return await get_columns_dict(self.connection, self.provider, self.app_label, table_name)
        
    async def test_create_model_operation(self):
        """Test CreateModel operation creates table with correct structure."""
        model_name = f"{self.app_label}.TestModel"
        fields = {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
            "created_at": DateTimeField(default=datetime.datetime.now),
            "active": BooleanField(default=True),
        }
        
        operation = CreateModel(model_name, fields)
        await operation.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        table_name = self._get_table_name("TestModel")
        self.assertTrue(await self._table_exists(table_name))
        
        columns = await self._get_table_columns(table_name)
        self.assertIn("id", columns)
        self.assertIn("name", columns) 
        self.assertIn("created_at", columns)
        self.assertIn("active", columns)
        
    async def test_add_field_operation(self):
        """Test AddField operation adds column correctly."""
        # First create a base model
        model_name = f"{self.app_label}.User"
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Add a field
        add_op = AddField(model_name, "age", IntegerField(null=True))
        await add_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        table_name = self._get_table_name("User")
        columns = await self._get_table_columns(table_name)
        self.assertIn("age", columns)
        self.assertEqual(columns["age"], "INTEGER")
        
    async def test_remove_field_operation(self):
        """Test RemoveField operation removes column correctly."""
        model_name = f"{self.app_label}.Product"
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
            "price": IntegerField(),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Remove the price field
        remove_op = RemoveField(model_name, "price")
        await remove_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        table_name = self._get_table_name("Product")
        columns = await self._get_table_columns(table_name)
        self.assertNotIn("price", columns)
        self.assertIn("name", columns)  # Other columns should remain
        
    async def test_rename_field_operation(self):
        """Test RenameField operation renames column correctly."""
        model_name = f"{self.app_label}.Article"
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "title": CharField(max_length=200),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Rename title to headline
        rename_op = RenameField(model_name, "title", "headline")
        await rename_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        table_name = self._get_table_name("Article")
        columns = await self._get_table_columns(table_name)
        self.assertNotIn("title", columns)
        self.assertIn("headline", columns)
        
    async def test_rename_model_operation(self):
        """Test RenameModel operation renames table correctly."""
        old_model = f"{self.app_label}.OldModel"
        new_model = f"{self.app_label}.NewModel"
        
        create_op = CreateModel(old_model, {
            "id": CharField(primary_key=True),
            "data": CharField(max_length=100),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Rename the model
        rename_op = RenameModel(old_model, new_model)
        await rename_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        old_table = self._get_table_name("OldModel")
        new_table = self._get_table_name("NewModel")
        
        self.assertFalse(await self._table_exists(old_table))
        self.assertTrue(await self._table_exists(new_table))
        
        # Verify columns are preserved
        columns = await self._get_table_columns(new_table)
        self.assertIn("id", columns)
        self.assertIn("data", columns)
        
    async def test_delete_model_operation(self):
        """Test DeleteModel operation drops table correctly."""
        model_name = f"{self.app_label}.TemporaryModel"
        
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "temp_data": CharField(max_length=50),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        table_name = self._get_table_name("TemporaryModel")
        self.assertTrue(await self._table_exists(table_name))
        
        # Delete the model
        delete_op = DeleteModel(model_name)
        await delete_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        self.assertFalse(await self._table_exists(table_name))


class TestComplexMigrations(IsolatedAsyncioTestCase):
    """Test complex migration scenarios with multiple operations."""

    def setUp(self):
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        self.app_label = f"complex_test_{unique_id}"

    async def asyncSetUp(self):
        conn = await get_databases().get_connection('default')
        self.connection = conn
        self.provider = conn.provider

    async def asyncTearDown(self):
        pass
        
    async def test_sequential_operations(self):
        """Test multiple operations in sequence within single migration."""
        operations = [
            CreateModel(f"{self.app_label}.Blog", {
                "id": CharField(primary_key=True),
                "title": CharField(max_length=200),
            }),
            AddField(f"{self.app_label}.Blog", "content", CharField(max_length=1000)),
            RenameField(f"{self.app_label}.Blog", "title", "headline"),
            AddField(f"{self.app_label}.Blog", "published", BooleanField(default=False)),
        ]
        
        migration = Migration(self.app_label, operations)
        await migration.apply({}, self.provider, self.connection)
        
        # Verify final state
        table_name = f"{self.app_label}_blog"
        from neutronapi.tests.db.test_utils import get_columns_dict
        columns = await get_columns_dict(self.connection, self.provider, self.app_label, table_name)
        column_names = list(columns.keys())
        self.assertIn("headline", column_names)  # renamed from title
        self.assertIn("content", column_names)   # added field
        self.assertIn("published", column_names) # added field
        self.assertNotIn("title", column_names)  # should be renamed
        
    async def test_model_evolution(self):
        """Test evolving a model through multiple migrations."""
        # Migration 1: Create initial model
        migration1 = Migration(self.app_label, [
            CreateModel(f"{self.app_label}.Customer", {
                "id": CharField(primary_key=True),
                "name": CharField(max_length=100),
            })
        ])
        await migration1.apply({}, self.provider, self.connection)
        
        # Migration 2: Add fields and rename
        migration2 = Migration(self.app_label, [
            AddField(f"{self.app_label}.Customer", "email", CharField(max_length=200)),
            RenameModel(f"{self.app_label}.Customer", f"{self.app_label}.Client"),
            AddField(f"{self.app_label}.Client", "active", BooleanField(default=True)),
        ])
        await migration2.apply({}, self.provider, self.connection)
        
        # Verify final state
        client_table = f"{self.app_label}_client"
        customer_table = f"{self.app_label}_customer"
        
        # Customer table should not exist
        from neutronapi.tests.db.test_utils import table_exists
        self.assertFalse(await table_exists(self.connection, self.provider, self.app_label, customer_table))
        
        # Client table should exist with all fields
        columns = await get_columns_dict(self.connection, self.provider, self.app_label, client_table)
        column_names = list(columns.keys())
        self.assertIn("id", column_names)
        self.assertIn("name", column_names)
        self.assertIn("email", column_names)
        self.assertIn("active", column_names)


class TestMigrationManager(IsolatedAsyncioTestCase):
    """Test the MigrationManager functionality."""
    
    async def asyncSetUp(self):
        self.db_alias = 'default'
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
        
        # Use default test DB
        conn = await get_databases().get_connection('default')
        self.connection = conn
        self.provider = conn.provider
        
    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir)
        
    async def test_discover_models(self):
        """Test model discovery functionality."""
        models = self.manager._discover_models(self.app_label)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].__name__, "TestModel")
        
    async def test_makemigrations_clean(self):
        """Test migration generation in clean mode."""
        models = self.manager._discover_models(self.app_label)
        operations = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=True
        )
        
        self.assertTrue(operations)
        self.assertEqual(len(operations), 1)
        self.assertIsInstance(operations[0], CreateModel)
        self.assertEqual(operations[0].model_name, f"{self.app_label}.TestModel")
        
    async def test_bootstrap_process(self):
        """Test the complete bootstrap process."""
        models = self.manager._discover_models(self.app_label)
        
        # Bootstrap should create tables
        db_alias, connection = await self.manager.bootstrap(
            app_label=self.app_label,
            models=models,
            db=self.db_alias,
            test_mode=True
        )
        
        self.assertEqual(db_alias, self.db_alias)
        
        # Verify table was created
        from neutronapi.tests.db.test_utils import table_exists
        self.assertTrue(await table_exists(connection, self.provider, self.app_label, f"{self.app_label}_test_model"))


# Legacy test class - keeping for backward compatibility but using new comprehensive tests above
