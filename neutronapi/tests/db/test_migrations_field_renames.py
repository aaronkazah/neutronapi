import unittest
import tempfile
import os
from unittest.mock import patch, Mock
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, TextField, IntegerField, BooleanField
from neutronapi.db.connection import setup_databases
from neutronapi.db.migrations import MigrationManager, RenameField


class TestFieldRenameModel(Model):
    """Test model for field rename operations"""
    name = CharField(max_length=100, null=False)
    description = TextField(null=True)
    age = IntegerField(null=True)
    active = BooleanField(default=True)


class TestMigrationsFieldRenames(unittest.IsolatedAsyncioTestCase):
    """Comprehensive tests for field rename detection and operations across SQLite/PostgreSQL"""

    async def asyncSetUp(self):
        # Create temporary SQLite database for tests
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        
        self.sqlite_config = {
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': self.temp_db.name,
            }
        }
        
        # Test both SQLite and PostgreSQL if available
        self.test_postgres = self._should_test_postgres()
        
        if self.test_postgres:
            from neutronapi.conf import settings
            self.postgres_config = settings.DATABASES.copy()

    async def asyncTearDown(self):
        if hasattr(self, 'db_manager'):
            await self.db_manager.close_all()
        if hasattr(self, 'temp_db') and self.temp_db:
            try:
                os.unlink(self.temp_db.name)
            except Exception:
                pass

    def _should_test_postgres(self):
        """Check if PostgreSQL testing is available"""
        try:
            import asyncpg
            from neutronapi.conf import settings
            db_config = settings.DATABASES.get('default', {})
            return db_config.get('ENGINE', '').lower() == 'asyncpg'
        except:
            return False

    async def _setup_database(self, use_postgres=False, model_suffix=""):
        """Setup database with appropriate configuration"""
        if use_postgres and self.test_postgres:
            self.db_manager = setup_databases(self.postgres_config)
        else:
            self.db_manager = setup_databases(self.sqlite_config)
        
        # Create initial table with unique name for each test
        from neutronapi.db.migrations import CreateModel
        connection = await self.db_manager.get_connection('default')
        model_name = f'test.TestFieldRenameModel{model_suffix}'
        op = CreateModel(model_name, TestFieldRenameModel._fields)
        await op.database_forwards(
            app_label='test',
            provider=connection.provider,
            from_state=None,
            to_state=None,
            connection=connection,
        )
        return connection

    def test_detect_field_renames_single_match(self):
        """Test detecting single field rename with matching types"""
        manager = MigrationManager("test_apps")
        
        # Mock model class with renamed field
        mock_model = Mock()
        mock_model._fields = {
            'new_name': Mock(),
            'description': Mock(),
        }
        mock_model._fields['new_name'].describe.return_value = "CharField(max_length=100, null=False)"
        mock_model._fields['description'].describe.return_value = "TextField(null=True)"
        
        added_fields = {'new_name'}
        deleted_fields = {'name'}
        current_fields_state = {
            'new_name': "CharField(max_length=100, null=False)",
            'description': "TextField(null=True)"
        }
        previous_fields_state = {
            'name': "CharField(max_length=100, null=False)",
            'description': "TextField(null=True)"
        }
        
        # Mock user input to confirm rename
        with patch('builtins.input', return_value='y'):
            renames = manager._detect_field_renames(
                model_name='TestModel',
                added_fields=added_fields,
                deleted_fields=deleted_fields,
                current_fields_state=current_fields_state,
                previous_fields_state=previous_fields_state,
                model_class=mock_model
            )
        
        self.assertEqual(renames, {'name': 'new_name'})

    def test_detect_field_renames_multiple_fields(self):
        """Test detecting multiple field renames"""
        manager = MigrationManager("test_apps")
        
        # Mock model class with multiple renamed fields
        mock_model = Mock()
        mock_model._fields = {
            'full_name': Mock(),
            'bio': Mock(),
        }
        mock_model._fields['full_name'].describe.return_value = "CharField(max_length=100, null=False)"
        mock_model._fields['bio'].describe.return_value = "TextField(null=True)"
        
        added_fields = {'full_name', 'bio'}
        deleted_fields = {'name', 'description'}
        current_fields_state = {
            'full_name': "CharField(max_length=100, null=False)",
            'bio': "TextField(null=True)"
        }
        previous_fields_state = {
            'name': "CharField(max_length=100, null=False)",
            'description': "TextField(null=True)"
        }
        
        # Mock user input to confirm both renames
        with patch('builtins.input', side_effect=['y', 'y']):
            renames = manager._detect_field_renames(
                model_name='TestModel',
                added_fields=added_fields,
                deleted_fields=deleted_fields,
                current_fields_state=current_fields_state,
                previous_fields_state=previous_fields_state,
                model_class=mock_model
            )
        
        self.assertEqual(len(renames), 2)
        self.assertIn('name', renames)
        self.assertIn('description', renames)

    def test_detect_field_renames_user_rejects(self):
        """Test when user rejects suggested rename"""
        manager = MigrationManager("test_apps")
        
        mock_model = Mock()
        mock_model._fields = {
            'new_name': Mock(),
        }
        mock_model._fields['new_name'].describe.return_value = "CharField(max_length=100, null=False)"
        
        added_fields = {'new_name'}
        deleted_fields = {'name'}
        current_fields_state = {'new_name': "CharField(max_length=100, null=False)"}
        previous_fields_state = {'name': "CharField(max_length=100, null=False)"}
        
        # Mock user input to reject rename
        with patch('builtins.input', return_value='n'):
            renames = manager._detect_field_renames(
                model_name='TestModel',
                added_fields=added_fields,
                deleted_fields=deleted_fields,
                current_fields_state=current_fields_state,
                previous_fields_state=previous_fields_state,
                model_class=mock_model
            )
        
        self.assertEqual(renames, {})

    def test_detect_field_renames_no_type_match(self):
        """Test detecting renames when field types don't match"""
        manager = MigrationManager("test_apps")
        
        mock_model = Mock()
        mock_model._fields = {
            'count': Mock(),
        }
        mock_model._fields['count'].describe.return_value = "IntegerField(null=True)"
        
        added_fields = {'count'}
        deleted_fields = {'name'}
        current_fields_state = {'count': "IntegerField(null=True)"}
        previous_fields_state = {'name': "CharField(max_length=100, null=False)"}
        
        # Should still prompt for 1-to-1 case even with different types
        with patch('builtins.input', return_value='y'):
            renames = manager._detect_field_renames(
                model_name='TestModel',
                added_fields=added_fields,
                deleted_fields=deleted_fields,
                current_fields_state=current_fields_state,
                previous_fields_state=previous_fields_state,
                model_class=mock_model
            )
        
        self.assertEqual(renames, {'name': 'count'})

    async def test_rename_field_operation_sqlite(self):
        """Test actual field rename operation on SQLite"""
        connection = await self._setup_database(use_postgres=False, model_suffix="SQLite")
        
        # Use the table name created by CreateModel operation (app_label + model_name)
        # "TestFieldRenameModelSQLite" becomes "test_field_rename_model_s_q_lite"
        table_name = "test_test_field_rename_model_s_q_lite"
        
        # Insert test data
        await connection.execute(
            f'INSERT INTO "{table_name}" (id, name, description, age, active) VALUES (?, ?, ?, ?, ?)',
            ('test1', 'John', 'A person', 25, True)
        )
        
        # Execute rename operation
        rename_op = RenameField(
            model_name='test.TestFieldRenameModelSQLite',
            old_field_name='name',
            new_field_name='full_name'
        )
        
        await rename_op.database_forwards(
            app_label='test',
            provider=connection.provider,
            from_state=None,
            to_state=None,
            connection=connection
        )
        
        # Verify the rename worked
        # Check that old column doesn't exist and new column does
        try:
            await connection.fetch_one(f'SELECT name FROM "{table_name}" LIMIT 1')
            self.fail("Old column 'name' should not exist")
        except Exception:
            pass  # Expected - old column shouldn't exist
        
        # Check new column exists and has the data
        row = await connection.fetch_one(f'SELECT full_name FROM "{table_name}" WHERE id = ?', ('test1',))
        self.assertEqual(row['full_name'], 'John')

    async def test_rename_field_operation_postgres(self):
        """Test actual field rename operation on PostgreSQL"""
        if not self.test_postgres:
            self.skipTest("PostgreSQL not available for testing")
        
        connection = await self._setup_database(use_postgres=True, model_suffix="Postgres")
        
        # Use the actual table name created by the provider
        # PostgreSQL creates schema.table_name format, so use the correct identifier
        # Model name "TestFieldRenameModelPostgres" becomes "test_field_rename_model_postgres" 
        table_identifier = connection.provider.get_table_identifier('test', 'test_field_rename_model_postgres')
        
        # Insert test data using the original column names from the model
        await connection.execute(
            f'INSERT INTO {table_identifier} (id, name, description, age, active) VALUES ($1, $2, $3, $4, $5)',
            ('test1', 'John', 'A person', 25, True)
        )
        
        # Execute rename operation  
        rename_op = RenameField(
            model_name='test.TestFieldRenameModelPostgres',
            old_field_name='name',
            new_field_name='full_name'
        )
        
        await rename_op.database_forwards(
            app_label='test',
            provider=connection.provider,
            from_state=None,
            to_state=None,
            connection=connection
        )
        
        # Verify the rename worked
        # Check that old column doesn't exist and new column does
        try:
            await connection.fetch_one(f'SELECT name FROM {table_identifier} LIMIT 1')
            self.fail("Old column 'name' should not exist")
        except Exception:
            pass  # Expected - old column shouldn't exist
        
        # Check new column exists and has the data
        row = await connection.fetch_one(f'SELECT full_name FROM {table_identifier} WHERE id = $1', ('test1',))
        self.assertEqual(row['full_name'], 'John')

    async def test_multiple_field_renames_sqlite(self):
        """Test multiple field renames in single migration on SQLite"""
        connection = await self._setup_database(use_postgres=False, model_suffix="MultiSQLite")
        
        # Use the table name created by CreateModel operation (app_label + model_name)
        # "TestFieldRenameModelMultiSQLite" becomes "test_field_rename_model_multi_s_q_lite"
        table_name = "test_test_field_rename_model_multi_s_q_lite"
        
        # Insert test data
        await connection.execute(
            f'INSERT INTO "{table_name}" (id, name, description, age, active) VALUES (?, ?, ?, ?, ?)',
            ('test1', 'John', 'A person', 25, True)
        )
        
        # Execute multiple rename operations
        rename_ops = [
            RenameField(
                model_name='test.TestFieldRenameModelMultiSQLite',
                old_field_name='name',
                new_field_name='full_name'
            ),
            RenameField(
                model_name='test.TestFieldRenameModelMultiSQLite',
                old_field_name='description',
                new_field_name='bio'
            )
        ]
        
        for op in rename_ops:
            await op.database_forwards(
                app_label='test',
                provider=connection.provider,
                from_state=None,
                to_state=None,
                connection=connection
            )
        
        # Verify both renames worked
        row = await connection.fetch_one(f'SELECT full_name, bio FROM "{table_name}" WHERE id = ?', ('test1',))
        self.assertEqual(row['full_name'], 'John')
        self.assertEqual(row['bio'], 'A person')

    async def test_multiple_field_renames_postgres(self):
        """Test multiple field renames in single migration on PostgreSQL"""
        if not self.test_postgres:
            self.skipTest("PostgreSQL not available for testing")
        
        connection = await self._setup_database(use_postgres=True, model_suffix="MultiPostgres")
        
        # Use the actual table name created by the provider
        # Model name "TestFieldRenameModelMultiPostgres" becomes "test_field_rename_model_multi_postgres"
        table_identifier = connection.provider.get_table_identifier('test', 'test_field_rename_model_multi_postgres')
        
        # Insert test data
        await connection.execute(
            f'INSERT INTO {table_identifier} (id, name, description, age, active) VALUES ($1, $2, $3, $4, $5)',
            ('test1', 'John', 'A person', 25, True)
        )
        
        # Execute multiple rename operations
        rename_ops = [
            RenameField(
                model_name='test.TestFieldRenameModelMultiPostgres',
                old_field_name='name',
                new_field_name='full_name'
            ),
            RenameField(
                model_name='test.TestFieldRenameModelMultiPostgres',
                old_field_name='description',
                new_field_name='bio'
            )
        ]
        
        for op in rename_ops:
            await op.database_forwards(
                app_label='test',
                provider=connection.provider,
                from_state=None,
                to_state=None,
                connection=connection
            )
        
        # Verify both renames worked
        row = await connection.fetch_one(f'SELECT full_name, bio FROM {table_identifier} WHERE id = $1', ('test1',))
        self.assertEqual(row['full_name'], 'John')
        self.assertEqual(row['bio'], 'A person')

    def test_field_rename_with_constraints(self):
        """Test field rename detection with various field constraints"""
        manager = MigrationManager("test_apps")
        
        # Test with unique constraint
        mock_model = Mock()
        mock_model._fields = {
            'unique_name': Mock(),
        }
        mock_model._fields['unique_name'].describe.return_value = "CharField(max_length=100, null=False, unique=True)"
        
        added_fields = {'unique_name'}
        deleted_fields = {'name'}
        current_fields_state = {'unique_name': "CharField(max_length=100, null=False, unique=True)"}
        previous_fields_state = {'name': "CharField(max_length=100, null=False, unique=True)"}
        
        with patch('builtins.input', return_value='y'):
            renames = manager._detect_field_renames(
                model_name='TestModel',
                added_fields=added_fields,
                deleted_fields=deleted_fields,
                current_fields_state=current_fields_state,
                previous_fields_state=previous_fields_state,
                model_class=mock_model
            )
        
        self.assertEqual(renames, {'name': 'unique_name'})


if __name__ == '__main__':
    unittest.main()