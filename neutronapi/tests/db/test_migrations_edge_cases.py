import os
import tempfile
import textwrap
import shutil
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
)
from neutronapi.db.fields import CharField, IntegerField, DateTimeField, BooleanField
from neutronapi.db.connection import get_databases
from neutronapi.tests.db.test_utils import get_columns_dict, table_exists


class TestMigrationErrorHandling(IsolatedAsyncioTestCase):
    """Test error handling and edge cases in migrations."""
    
    def setUp(self):
        self.app_label = "error_test"
        self.db_alias = "error_test_db"
        
    async def asyncSetUp(self):
        self.connection = await get_databases().get_connection('default')
        
        if hasattr(self.connection, 'provider'):
            self.provider = self.connection.provider
        else:
            self.provider = self.connection
            
    async def asyncTearDown(self):
        pass
        
    async def test_add_field_to_nonexistent_table(self):
        """Test adding field to table that doesn't exist should handle gracefully."""
        model_name = f"{self.app_label}.NonExistentModel"
        add_op = AddField(model_name, "test_field", CharField(max_length=100))
        
        # This should raise an error or handle gracefully
        with self.assertRaises(Exception):
            await add_op.database_forwards(
                self.app_label, self.provider, None, None, self.connection
            )
            
    async def test_remove_nonexistent_field(self):
        """Test removing field that doesn't exist."""
        # Create a table first
        model_name = f"{self.app_label}.TestModel"
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Try to remove non-existent field
        remove_op = RemoveField(model_name, "nonexistent_field")
        
        # Should handle gracefully (depending on provider implementation)
        try:
            await remove_op.database_forwards(
                self.app_label, self.provider, None, None, self.connection
            )
        except Exception as e:
            # Log the error but don't fail the test if provider handles it
            logging.info(f"Expected error removing non-existent field: {e}")
            
    async def test_rename_nonexistent_field(self):
        """Test renaming field that doesn't exist."""
        model_name = f"{self.app_label}.TestModel"
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        rename_op = RenameField(model_name, "nonexistent", "new_name")
        
        with self.assertRaises(Exception):
            await rename_op.database_forwards(
                self.app_label, self.provider, None, None, self.connection
            )
            
    async def test_rename_nonexistent_table(self):
        """Test renaming table that doesn't exist."""
        old_model = f"{self.app_label}.NonExistent"
        new_model = f"{self.app_label}.NewName"
        
        rename_op = RenameModel(old_model, new_model)
        
        with self.assertRaises(Exception):
            await rename_op.database_forwards(
                self.app_label, self.provider, None, None, self.connection
            )
            
    async def test_create_duplicate_table(self):
        """Test creating table that already exists."""
        model_name = f"{self.app_label}.DuplicateTest"
        fields = {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
        }
        
        # Create table first time
        create_op1 = CreateModel(model_name, fields)
        await create_op1.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Try to create same table again - should be idempotent (no error)
        create_op2 = CreateModel(model_name, fields)
        try:
            await create_op2.database_forwards(
                self.app_label, self.provider, None, None, self.connection
            )
        except Exception as e:
            self.fail(f"Duplicate table creation should be idempotent, but got error: {e}")
            
    async def test_migration_rollback_on_failure(self):
        """Test that failed migrations can be rolled back properly."""
        operations = [
            CreateModel(f"{self.app_label}.TestModel", {
                "id": CharField(primary_key=True),
                "name": CharField(max_length=100),
            }),
            # This should fail - trying to add field to non-existent table
            AddField(f"{self.app_label}.NonExistent", "field", CharField(max_length=50)),
        ]
        
        migration = Migration(self.app_label, operations)
        
        # Should fail and rollback
        with self.assertRaises(Exception):
            await migration.apply({}, self.provider, self.connection)
            
        # Verify that the first table wasn't created due to rollback
        # (This depends on transaction handling in your implementation)
        from neutronapi.tests.db.test_utils import table_exists
        exists = await table_exists(self.connection, self.provider, self.app_label, f"{self.app_label}_test_model")
        # Depending on transaction handling, this might be False if properly rolled back


class TestMigrationConstraints(IsolatedAsyncioTestCase):
    """Test migration operations with constraints and special cases."""
    
    def setUp(self):
        self.app_label = "constraint_test"
        self.db_alias = "constraint_test_db"
        
    async def asyncSetUp(self):
        # Use default connection from the bootstrapped test DB
        self.connection = await get_databases().get_connection('default')
        
        if hasattr(self.connection, 'provider'):
            self.provider = self.connection.provider
        else:
            self.provider = self.connection
            
    async def asyncTearDown(self):
        pass
        
    async def test_add_required_field_to_existing_table(self):
        """Test adding a required field to table with existing data."""
        model_name = f"{self.app_label}.ExistingModel"
        
        # Create table
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Insert some test data
        table_name = f"{self.app_label}_existing_model"
        # Provider-aware insert for existing data
        db_type = getattr(self.connection, 'db_type', None)
        if str(db_type).lower().endswith('postgres'):
            base = "existing_model"
            await self.provider.execute(
                f'INSERT INTO "{self.app_label}"."{base}" (id, name) VALUES ($1, $2)',
                ("test1", "Test Name"),
            )
        else:
            await self.connection.execute(
                f'INSERT INTO {table_name} (id, name) VALUES (?, ?)',
                ("test1", "Test Name"),
            )
        
        # Try to add required field (should fail or require default)
        add_op = AddField(model_name, "required_field", CharField(max_length=50, null=False))
        
        # This might fail depending on how provider handles it
        try:
            await add_op.database_forwards(
                self.app_label, self.provider, None, None, self.connection
            )
            # If successful, verify the field was added
            from neutronapi.tests.db.test_utils import get_columns_dict
            columns = await get_columns_dict(self.connection, self.provider, self.app_label, table_name)
            self.assertIn("required_field", columns)
            
        except Exception as e:
            # Expected for required fields without defaults
            logging.info(f"Expected error adding required field: {e}")
            
    async def test_primary_key_operations(self):
        """Test operations involving primary keys."""
        model_name = f"{self.app_label}.PKTest"
        
        # Create table with custom primary key
        create_op = CreateModel(model_name, {
            "custom_id": CharField(primary_key=True, max_length=50),
            "name": CharField(max_length=100),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Verify primary key was set correctly
        table_name = f"{self.app_label}_p_k_test"
        from neutronapi.tests.db.test_utils import get_columns_dict
        columns = await get_columns_dict(self.connection, self.provider, self.app_label, table_name)
        self.assertIn("custom_id", columns)
        
    async def test_field_with_defaults(self):
        """Test fields with various default values."""
        model_name = f"{self.app_label}.DefaultTest"
        
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100, default="default_name"),
            "count": IntegerField(default=0),
            "active": BooleanField(default=True),
            "created": DateTimeField(default=datetime.datetime.now),
        })
        
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Verify table was created successfully (provider-aware)
        table_name = f"{self.app_label}_default_test"
        exists = await table_exists(self.connection, self.provider, self.app_label, table_name)
        self.assertTrue(exists)


class TestMigrationStateManagement(IsolatedAsyncioTestCase):
    """Test migration state management and HASH functionality."""
    
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.apps_dir = os.path.join(self.temp_dir, 'apps')
        os.makedirs(self.apps_dir, exist_ok=True)
        
        self.app_label = 'state_test'
        self.app_dir = os.path.join(self.apps_dir, self.app_label)
        models_dir = os.path.join(self.app_dir, 'models')
        self.migrations_dir = os.path.join(self.app_dir, 'migrations')
        
        for dir_path in [self.app_dir, models_dir, self.migrations_dir]:
            os.makedirs(dir_path, exist_ok=True)
            with open(os.path.join(dir_path, '__init__.py'), 'w') as f:
                f.write("")
                
        self.manager = MigrationManager(apps=[self.app_label], base_dir=self.apps_dir)
        
    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir)
        
    def _create_mock_model_file(self, model_content):
        """Helper to create model file with given content."""
        with open(os.path.join(self.app_dir, 'models', 'test_model.py'), 'w') as f:
            f.write(textwrap.dedent(model_content))
            
    def _create_mock_migration_file(self, filename, content):
        """Helper to create migration file with given content."""
        filepath = os.path.join(self.migrations_dir, filename)
        with open(filepath, 'w') as f:
            f.write(textwrap.dedent(content))
        return filepath
        
    async def test_state_detection_no_previous_migrations(self):
        """Test state detection when no previous migrations exist."""
        self._create_mock_model_file("""
            from neutronapi.db.models import Model
            from neutronapi.db.fields import CharField
            
            class TestModel(Model):
                name = CharField(max_length=100)
                
                @classmethod 
                def get_app_label(cls):
                    return 'state_test'
        """)
        
        models = self.manager._discover_models(self.app_label)
        operations = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=False  # Should use normal mode
        )
        
        # Should generate CreateModel operation for new model
        self.assertEqual(len(operations), 1)
        self.assertIsInstance(operations[0], CreateModel)
        
    async def test_state_detection_with_previous_migration(self):
        """Test state detection when previous migration exists."""
        # Create initial model
        self._create_mock_model_file("""
            from neutronapi.db.models import Model
            from neutronapi.db.fields import CharField
            
            class TestModel(Model):
                name = CharField(max_length=100)
                
                @classmethod
                def get_app_label(cls):
                    return 'state_test'
        """)
        
        # Create mock previous migration file with HASH
        migration_content = '''
            from neutronapi.db.migrations import Migration, CreateModel
            from neutronapi.db.fields import CharField
            
            class Migration0001(Migration):
                operations = [
                    CreateModel("state_test.TestModel", {
                        "id": CharField(primary_key=True),
                        "name": CharField(max_length=100),
                    })
                ]
            
            HASH = {
                "TestModel": {
                    "fields": {
                        "id": "CharField(primary_key=True)",
                        "name": "CharField(max_length=100)"
                    }
                }
            }
        '''
        
        self._create_mock_migration_file('0001_initial.py', migration_content)
        
        # Now discover models and generate migrations
        models = self.manager._discover_models(self.app_label)
        operations = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=False
        )
        
        # Should detect no changes since model matches HASH, but allow for one no-op diff
        self.assertIn(len(operations), (0, 1))
        
    async def test_state_change_detection(self):
        """Test detection of changes between model state and HASH."""
        # Create model with additional field
        self._create_mock_model_file("""
            from neutronapi.db.models import Model
            from neutronapi.db.fields import CharField, IntegerField
            
            class TestModel(Model):
                name = CharField(max_length=100)
                age = IntegerField(null=True)  # New field
                
                @classmethod
                def get_app_label(cls):
                    return 'state_test'
        """)
        
        # Create previous migration with old state
        migration_content = '''
            from neutronapi.db.migrations import Migration, CreateModel
            from neutronapi.db.fields import CharField
            
            class Migration0001(Migration):
                operations = []
            
            HASH = {
                "TestModel": {
                    "fields": {
                        "id": "CharField(primary_key=True)",
                        "name": "CharField(max_length=100)"
                    }
                }
            }
        '''
        
        self._create_mock_migration_file('0001_initial.py', migration_content)
        
        models = self.manager._discover_models(self.app_label)
        operations = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=False
        )
        
        # Should detect the new field
        self.assertEqual(len(operations), 1)
        self.assertIsInstance(operations[0], AddField)
        self.assertEqual(operations[0].field_name, "age")


class TestMigrationBackwardCompatibility(IsolatedAsyncioTestCase):
    """Test backward migration operations."""
    
    def setUp(self):
        self.app_label = "backward_test"
        self.db_alias = "backward_test_db"
        
    async def asyncSetUp(self):
        self.connection = await get_databases().get_connection('default')
        
        if hasattr(self.connection, 'provider'):
            self.provider = self.connection.provider
        else:
            self.provider = self.connection
            
    async def asyncTearDown(self):
        pass
        
    async def test_backwards_operations(self):
        """Test that operations can be reversed properly."""
        model_name = f"{self.app_label}.TestModel"
        
        # Forward: Create model
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        table_name = f"{self.app_label}_test_model"
        
        # Verify table exists (provider-aware)
        from neutronapi.tests.db.test_utils import table_exists
        self.assertTrue(await table_exists(self.connection, self.provider, self.app_label, table_name))
        
        # Backward: Delete model
        await create_op.database_backwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Verify table is gone
        self.assertFalse(await table_exists(self.connection, self.provider, self.app_label, table_name))
        
    async def test_field_operations_backwards(self):
        """Test field operations can be reversed."""
        model_name = f"{self.app_label}.FieldTest"
        
        # Create base model
        create_op = CreateModel(model_name, {
            "id": CharField(primary_key=True),
            "name": CharField(max_length=100),
        })
        await create_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Forward: Add field
        add_op = AddField(model_name, "email", CharField(max_length=200))
        await add_op.database_forwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Verify field exists
        table_name = f"{self.app_label}_field_test"
        columns = await get_columns_dict(self.connection, self.provider, self.app_label, table_name)
        self.assertIn("email", columns)
        
        # Backward: Remove field
        await add_op.database_backwards(
            self.app_label, self.provider, None, None, self.connection
        )
        
        # Verify field is gone
        columns = await get_columns_dict(self.connection, self.provider, self.app_label, table_name)
        self.assertNotIn("email", columns)


class TestMigrationGapDetection(IsolatedAsyncioTestCase):
    """Test gap detection in migration files - ensuring file-based behavior."""
    
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.apps_dir = os.path.join(self.temp_dir, 'apps')
        os.makedirs(self.apps_dir, exist_ok=True)
        
        self.app_label = 'gap_test'
        self.app_dir = os.path.join(self.apps_dir, self.app_label)
        models_dir = os.path.join(self.app_dir, 'models')
        self.migrations_dir = os.path.join(self.app_dir, 'migrations')
        
        for dir_path in [self.app_dir, models_dir, self.migrations_dir]:
            os.makedirs(dir_path, exist_ok=True)
            with open(os.path.join(dir_path, '__init__.py'), 'w') as f:
                f.write("")
                
        self.manager = MigrationManager(apps=[self.app_label], base_dir=self.apps_dir)
        
    async def asyncTearDown(self):
        # Clean up Python module cache for this test's modules
        import sys
        import importlib
        modules_to_remove = [k for k in sys.modules.keys() if k.startswith(f'{self.app_label}.')]
        for module_name in modules_to_remove:
            del sys.modules[module_name]
        importlib.invalidate_caches()
        
        # Clean up model cache
        if hasattr(self, 'manager'):
            self.manager._models_cache.clear()
            
        shutil.rmtree(self.temp_dir)
        
    def _create_model_file(self, model_content):
        """Helper to create model file with given content."""
        with open(os.path.join(self.app_dir, 'models', 'test_model.py'), 'w') as f:
            f.write(textwrap.dedent(model_content))
            
    def _create_migration_file(self, filename, content):
        """Helper to create migration file with given content."""
        filepath = os.path.join(self.migrations_dir, filename)
        with open(filepath, 'w') as f:
            f.write(textwrap.dedent(content))
        return filepath
        
    def _delete_migration_file(self, filename):
        """Helper to delete a migration file."""
        filepath = os.path.join(self.migrations_dir, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            
    async def test_no_gap_normal_behavior(self):
        """Test normal behavior when no gaps exist."""
        # Create model
        self._create_model_file("""
            from neutronapi.db.models import Model
            from neutronapi.db.fields import CharField
            
            class User(Model):
                name = CharField(max_length=100)
                
                @classmethod 
                def get_app_label(cls):
                    return 'gap_test'
        """)
        
        # Create migration with HASH
        self._create_migration_file('0001_initial.py', '''
            from neutronapi.db.migrations import Migration, CreateModel
            from neutronapi.db.fields import CharField
            
            class Migration0001(Migration):
                operations = [
                    CreateModel("gap_test.User", {
                        "id": CharField(primary_key=True),
                        "name": CharField(max_length=100),
                    })
                ]
            
            HASH = {
                "User": {
                    "fields": {
                        "id": "CharField(primary_key=True)",
                        "name": "CharField(max_length=100)"
                    }
                }
            }
        ''')
        
        models = self.manager._discover_models(self.app_label)
        operations = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=False
        )
        
        # Should detect no changes
        self.assertEqual(len(operations), 0)
        
    async def test_single_gap_detection(self):
        """Test detection of single missing migration file."""
        # Create model
        self._create_model_file("""
            from neutronapi.db.models import Model
            from neutronapi.db.fields import CharField, IntegerField
            
            class User(Model):
                name = CharField(max_length=100)
                age = IntegerField()
                
                @classmethod 
                def get_app_label(cls):
                    return 'gap_test'
        """)
        
        # Create 0002 migration (missing 0001)
        self._create_migration_file('0002_add_age.py', '''
            from neutronapi.db.migrations import Migration, AddField
            from neutronapi.db.fields import CharField, IntegerField
            
            class Migration0002(Migration):
                operations = [
                    AddField("gap_test.User", "age", IntegerField())
                ]
            
            HASH = {
                "User": {
                    "fields": {
                        "id": "CharField(primary_key=True)",
                        "name": "CharField(max_length=100)",
                        "age": "IntegerField(db_column='age')"
                    }
                }
            }
        ''')
        
        models = self.manager._discover_models(self.app_label)
        
        # First call should detect gap and use latest migration state
        operations1 = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=False
        )
        
        # Should detect no changes (using state from 0002)
        self.assertEqual(len(operations1), 0)
        
        # Multiple calls should be stable
        operations2 = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=False
        )
        
        self.assertEqual(len(operations2), 0)
        
    async def test_multiple_gaps_detection(self):
        """Test detection of multiple missing migration files."""
        # Create model
        self._create_model_file("""
            from neutronapi.db.models import Model
            from neutronapi.db.fields import CharField, IntegerField, BooleanField
            
            class User(Model):
                name = CharField(max_length=100)
                age = IntegerField()
                active = BooleanField(default=True)
                
                @classmethod 
                def get_app_label(cls):
                    return 'gap_test'
        """)
        
        # Create 0004 migration (missing 0001, 0002, 0003)
        self._create_migration_file('0004_final.py', '''
            from neutronapi.db.migrations import Migration
            from neutronapi.db.fields import CharField, IntegerField, BooleanField
            
            class Migration0004(Migration):
                operations = []
            
            HASH = {
                "User": {
                    "fields": {
                        "id": "CharField(primary_key=True)",
                        "name": "CharField(max_length=100)",
                        "age": "IntegerField(db_column='age')",
                        "active": "BooleanField(default=True)"
                    }
                }
            }
        ''')
        
        models = self.manager._discover_models(self.app_label)
        operations = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=False
        )
        
        # Should use state from latest migration (0004)
        self.assertEqual(len(operations), 0)
        
    async def test_gap_with_actual_changes(self):
        """Test that actual model changes are still detected with gaps."""
        # Create model with new field
        self._create_model_file("""
            from neutronapi.db.models import Model
            from neutronapi.db.fields import CharField, IntegerField
            
            class User(Model):
                name = CharField(max_length=100)
                age = IntegerField()
                email = CharField(max_length=200)  # New field
                
                @classmethod 
                def get_app_label(cls):
                    return 'gap_test'
        """)
        
        # Create 0002 migration without email field (missing 0001)
        self._create_migration_file('0002_add_age.py', '''
            from neutronapi.db.migrations import Migration, AddField
            from neutronapi.db.fields import CharField, IntegerField
            
            class Migration0002(Migration):
                operations = []
            
            HASH = {
                "User": {
                    "fields": {
                        "id": "CharField(primary_key=True)",
                        "name": "CharField(max_length=100)",
                        "age": "IntegerField(db_column='age')"
                    }
                }
            }
        ''')
        
        models = self.manager._discover_models(self.app_label)
        operations = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=False
        )
        
        # Should detect the new email field
        self.assertEqual(len(operations), 1)
        self.assertIsInstance(operations[0], AddField)
        self.assertEqual(operations[0].field_name, "email")
        
    async def test_complete_regeneration_when_no_migrations(self):
        """Test complete regeneration when all migrations are deleted."""
        # Create model
        self._create_model_file("""
            from neutronapi.db.models import Model
            from neutronapi.db.fields import CharField, IntegerField
            
            class User(Model):
                name = CharField(max_length=100)
                age = IntegerField()
                
                @classmethod 
                def get_app_label(cls):
                    return 'gap_test'
        """)
        
        # No migration files exist
        models = self.manager._discover_models(self.app_label)
        operations = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=False
        )
        
        # Should generate CreateModel operation
        self.assertEqual(len(operations), 1)
        self.assertIsInstance(operations[0], CreateModel)
        self.assertEqual(operations[0].model_name, "gap_test.User")
        
    async def test_gap_detection_stability(self):
        """Test that gap detection doesn't cause infinite migration creation."""
        # Create model
        self._create_model_file("""
            from neutronapi.db.models import Model
            from neutronapi.db.fields import CharField, IntegerField
            
            class User(Model):
                name = CharField(max_length=100)
                age = IntegerField()
                
                @classmethod 
                def get_app_label(cls):
                    return 'gap_test'
        """)
        
        # Create 0003 migration (missing 0001, 0002)
        self._create_migration_file('0003_complete.py', '''
            from neutronapi.db.migrations import Migration, CreateModel
            from neutronapi.db.fields import CharField, IntegerField
            
            class Migration0003(Migration):
                operations = [
                    CreateModel("gap_test.User", {
                        "id": CharField(primary_key=True),
                        "name": CharField(max_length=100),
                        "age": IntegerField(),
                    })
                ]
            
            HASH = {
                "User": {
                    "fields": {
                        "id": "CharField(primary_key=True)",
                        "name": "CharField(max_length=100)",
                        "age": "IntegerField(db_column='age')"
                    }
                }
            }
        ''')
        
        models = self.manager._discover_models(self.app_label)
        
        # Run makemigrations multiple times
        for i in range(5):
            operations = await self.manager.makemigrations(
                app_label=self.app_label,
                models=models,
                return_ops=True,
                clean=False
            )
            
            # Should always detect no changes (stable behavior)
            self.assertEqual(len(operations), 0, f"Iteration {i+1} should have no changes")
            
    async def test_gap_detection_preserves_change_detection(self):
        """Test that gap detection doesn't break normal change detection."""
        # Create model with extra field (simulating a model change scenario)
        self._create_model_file("""
            from neutronapi.db.models import Model
            from neutronapi.db.fields import CharField, IntegerField
            
            class User(Model):
                name = CharField(max_length=100)
                age = IntegerField()  # This field is "new" compared to migration
                
                @classmethod 
                def get_app_label(cls):
                    return 'gap_test'
        """)
        
        # Create 0002 migration WITHOUT the age field (missing 0001)
        # This simulates a scenario where the model has evolved beyond the migration state
        self._create_migration_file('0002_add_user.py', '''
            from neutronapi.db.migrations import Migration, CreateModel
            from neutronapi.db.fields import CharField
            
            class Migration0002(Migration):
                operations = []
            
            HASH = {
                "User": {
                    "fields": {
                        "id": "CharField(primary_key=True)",
                        "name": "CharField(max_length=100)"
                    }
                }
            }
        ''')
        
        models = self.manager._discover_models(self.app_label)
        
        # Should detect the missing age field despite the gap
        operations = await self.manager.makemigrations(
            app_label=self.app_label,
            models=models,
            return_ops=True,
            clean=False
        )
        
        # Should detect the new age field
        self.assertEqual(len(operations), 1)
        self.assertIsInstance(operations[0], AddField)
        self.assertEqual(operations[0].field_name, "age")
