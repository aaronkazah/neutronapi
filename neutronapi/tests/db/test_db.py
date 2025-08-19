"""
Comprehensive tests for the database layer.
Tests models, migrations, fields, and database operations.
"""
import unittest
import asyncio
import tempfile
import os
from datetime import datetime

from neutronapi.db import setup_databases, get_databases
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField, IntegerField, DateTimeField, JSONField, BooleanField
from neutronapi.db.migrations import MigrationManager, CreateModel


class SampleModel(Model):
    """Test model for database operations."""
    name = CharField(max_length=100)
    age = IntegerField(null=True)
    created_at = DateTimeField(default=datetime.now)
    metadata = JSONField(default=dict)
    is_active = BooleanField(default=True)


class TestDatabaseSetup(unittest.TestCase):
    """Test database setup and configuration."""
    
    def setUp(self):
        # Preserve existing manager config to restore after test
        self._prev_config = get_databases().config.copy()

    def test_setup_databases(self):
        """Test database setup with custom config."""
        config = {
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': ':memory:'
            },
            'test_db': {
                'ENGINE': 'aiosqlite', 
                'NAME': '/tmp/test.db'
            }
        }
        
        db_manager = setup_databases(config)
        assert db_manager is not None
        assert db_manager.config == config

    def tearDown(self):
        # Restore original global manager config
        try:
            setup_databases(self._prev_config)
        except Exception:
            # As a fallback, rebuild based on env
            setup_databases(None)
    
    def test_get_databases_default(self):
        """Test getting databases with default config."""
        db_manager = get_databases()
        assert db_manager is not None
        assert 'default' in db_manager.config


class TestModelFunctionality(unittest.TestCase):
    """Test model functionality."""
    
    def setUp(self):
        """No per-test DB wiring; default test DB is bootstrapped by manage.py."""
        pass
    
    def test_model_creation(self):
        """Test creating a model instance."""
        user = SampleModel(
            name="John Doe",
            age=30,
            metadata={"role": "admin"}
        )
        
        self.assertEqual(user.name, "John Doe")
        self.assertEqual(user.age, 30)
        self.assertEqual(user.metadata, {"role": "admin"})
        self.assertTrue(user.is_active)  # Default value
        self.assertIsNotNone(user.created_at)  # Default datetime
    
    def test_model_fields_discovery(self):
        """Test that model fields are properly discovered."""
        fields = SampleModel._fields
        
        self.assertIn('id', fields)
        self.assertIn('name', fields)
        self.assertIn('age', fields)
        self.assertIn('created_at', fields)
        self.assertIn('metadata', fields)
        self.assertIn('is_active', fields)
        
        # Test field types
        self.assertIsInstance(fields['name'], CharField)
        self.assertIsInstance(fields['age'], IntegerField)
        self.assertIsInstance(fields['created_at'], DateTimeField)
        self.assertIsInstance(fields['metadata'], JSONField)
        self.assertIsInstance(fields['is_active'], BooleanField)
    
    def test_model_describe(self):
        """Test model field descriptions."""
        description = SampleModel.describe()
        
        self.assertIn('fields', description)
        self.assertIn('name', description['fields'])
        self.assertIn('CharField', description['fields']['name'])


class TestFields(unittest.TestCase):
    """Test field functionality."""
    
    def test_char_field_validation(self):
        """Test CharField validation."""
        field = CharField(max_length=10)
        
        # Should not raise for valid strings
        try:
            field.validate("test")
            field.validate("short")
        except Exception:
            self.fail("CharField validation failed for valid strings")
        
        # Should raise for strings that are too long
        with self.assertRaises(Exception):
            field.validate("this string is way too long")
        
        # Should raise for None if not nullable
        field.null = False
        with self.assertRaises(Exception):
            field.validate(None)
    
    def test_integer_field_validation(self):
        """Test IntegerField validation."""
        field = IntegerField()
        
        # Should not raise for valid integers
        field.validate(42)
        field.validate(-10)
        field.validate(0)
        
        # Should handle string numbers
        field.validate("123")
    
    def test_boolean_field_conversion(self):
        """Test BooleanField data conversion."""
        field = BooleanField()
        
        # Test to_db conversion
        assert field.to_db(True) is True
        assert field.to_db(False) is False
        assert field.to_db(1) is True
        assert field.to_db(0) is False
        
        # Test from_db conversion
        assert field.from_db(True) is True
        assert field.from_db(False) is False
        assert field.from_db(1) is True
        assert field.from_db(0) is False
    
    def test_json_field_serialization(self):
        """Test JSONField serialization."""
        field = JSONField()
        
        test_data = {"key": "value", "number": 42}
        
        # Test to_db (should return JSON string)
        db_value = field.to_db(test_data)
        assert isinstance(db_value, str)
        
        # Test from_db (should parse JSON back to dict)
        python_value = field.from_db(db_value)
        assert python_value == test_data
    
    def test_datetime_field_handling(self):
        """Test DateTimeField handling."""
        field = DateTimeField()
        now = datetime.now()
        
        # Test to_db
        db_value = field.to_db(now)
        assert isinstance(db_value, datetime)
        
        # Test from_db
        python_value = field.from_db(db_value)
        assert isinstance(python_value, datetime)
        assert python_value == now


class TestMigrations(unittest.TestCase):
    """Test migration system."""

    def setUp(self):
        """Setup test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.apps_dir = os.path.join(self.temp_dir, 'apps')
        os.makedirs(self.apps_dir)
        
        # Create test app structure
        test_app_dir = os.path.join(self.apps_dir, 'testapp')
        os.makedirs(test_app_dir)
        os.makedirs(os.path.join(test_app_dir, 'models'))
        os.makedirs(os.path.join(test_app_dir, 'migrations'))
        
        # Create __init__.py files
        open(os.path.join(test_app_dir, '__init__.py'), 'w').close()
        open(os.path.join(test_app_dir, 'models', '__init__.py'), 'w').close()
        open(os.path.join(test_app_dir, 'migrations', '__init__.py'), 'w').close()
    
    def tearDown(self):
        """Cleanup test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_migration_manager_init(self):
        """Test MigrationManager initialization."""
        manager = MigrationManager(base_dir=self.apps_dir)
        assert manager.base_dir == self.apps_dir
        assert isinstance(manager.apps, list)
    
    def test_create_model_operation(self):
        """Test CreateModel operation."""
        fields = {
            'id': CharField(primary_key=True),
            'name': CharField(max_length=100),
            'age': IntegerField()
        }
        
        operation = CreateModel('testapp.TestModel', fields)
        assert operation.model_name == 'testapp.TestModel'
        assert operation.fields == fields
        
        # Test description
        description = operation.describe()
        assert 'CreateModel' in description
        assert 'testapp.TestModel' in description


class TestDatabaseOperations(unittest.IsolatedAsyncioTestCase):
    """Test actual database operations using the Database/SQLite provider."""

    async def asyncSetUp(self):
        # Use default provider from bootstrapped test DB
        conn = await get_databases().get_connection('default')
        self.provider = conn.provider

        # Create a test table; adapt DDL per engine
        is_sqlite = 'sqlite' in self.provider.__class__.__name__.lower()
        if is_sqlite:
            ddl = (
                "CREATE TABLE test_table (\n"
                "    id INTEGER PRIMARY KEY,\n"
                "    name TEXT NOT NULL,\n"
                "    value INTEGER\n"
                ")"
            )
        else:
            ddl = (
                "CREATE TABLE IF NOT EXISTS test_table (\n"
                "    id SERIAL PRIMARY KEY,\n"
                "    name TEXT NOT NULL,\n"
                "    value INTEGER\n"
                ")"
            )
        await self.provider.execute(ddl)

    async def asyncTearDown(self):
        # Drop the ephemeral table to avoid clashes across tests
        try:
            await self.provider.execute("DROP TABLE IF EXISTS test_table")
        except Exception:
            pass

    async def test_database_connection(self):
        self.assertIsNotNone(self.provider)
        self.assertTrue(hasattr(self.provider, 'execute'))
        self.assertTrue(hasattr(self.provider, 'fetchone'))
        self.assertTrue(hasattr(self.provider, 'fetchall'))

    async def test_database_operations(self):
        # Insert/query with provider-specific placeholders
        is_sqlite = 'sqlite' in self.provider.__class__.__name__.lower()
        if is_sqlite:
            await self.provider.execute(
                "INSERT INTO test_table (name, value) VALUES (?, ?)",
                ("test", 42),
            )
            result = await self.provider.fetchone(
                "SELECT * FROM test_table WHERE name = ?",
                ("test",),
            )
        else:
            await self.provider.execute(
                "INSERT INTO test_table (name, value) VALUES ($1, $2)",
                ("test", 42),
            )
            result = await self.provider.fetchone(
                "SELECT * FROM test_table WHERE name = $1",
                ("test",),
            )
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'test')
        self.assertEqual(result['value'], 42)

        # Query all data
        results = await self.provider.fetchall("SELECT * FROM test_table")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], 'test')
