import unittest
import os
import tempfile
import datetime
from enum import Enum
from neutronapi.db import Model
from neutronapi.db.fields import CharField, JSONField, DateTimeField, EnumField
from neutronapi.db.connection import setup_databases
from neutronapi.db.queryset import QuerySet


class TestStatus(Enum):
    PENDING = "pending"
    RUNNING = "running" 
    COMPLETED = "completed"


class TestObject(Model):
    """Test model for QuerySet testing."""
    key = CharField(null=False)
    name = CharField(null=True)
    kind = CharField(null=True)
    folder = CharField(null=True)  
    parent = CharField(null=True)
    meta = JSONField(null=True, default=dict)
    store = JSONField(null=True, default=dict)
    connections = JSONField(null=True, default=dict)
    expires = DateTimeField(null=True)
    status = EnumField(TestStatus, null=True)


class TestQuerySetMoreSQLite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Create temporary SQLite database for testing
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        
        # Setup database configuration
        db_config = {
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': self.temp_db.name,
            }
        }
        self.db_manager = setup_databases(db_config)
        
        # Create the table using migration system
        from neutronapi.db.migrations import CreateModel
        connection = await self.db_manager.get_connection()
        
        # Create table for TestObject model using migrations
        create_operation = CreateModel('neutronapi.TestObject', TestObject._fields)
        await create_operation.database_forwards(
            app_label='neutronapi',
            provider=connection.provider, 
            from_state=None,
            to_state=None,
            connection=connection
        )

        # Seed data with duplicates and JSON numbers using Model.objects.create
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        past = now - datetime.timedelta(hours=1)
        future = now + datetime.timedelta(hours=1)

        await TestObject.objects.create(
            id="obj-3",
            key="/org-1/files/c.txt",
            name="C",
            kind="file",
            meta={"tag": "alpha", "score": 10, "type": "google"},
            folder="/org-1/files",
            parent="/org-1",
            expires=past,  # Expired
            status=TestStatus.COMPLETED,
        )
        await TestObject.objects.create(
            id="obj-4",
            key="/org-1/files/d.txt",
            name="A",
            kind="file",
            meta={"tag": "alpha", "score": 3, "type": "dropbox"},
            folder="/org-1/files",
            parent="/org-1",
            expires=future,  # Not expired
            status=TestStatus.RUNNING,
        )
        await TestObject.objects.create(
            id="obj-5",
            key="/org-1/files/e.txt",
            name="E",
            kind="file", 
            meta={"tag": "beta", "score": 7, "type": "google"},
            folder="/org-1/files",
            parent="/org-1",
            expires=future,  # Not expired
            status=TestStatus.PENDING,
        )

    async def asyncTearDown(self):
        await self.db_manager.close_all()
        os.unlink(self.temp_db.name)

    async def test_values_and_exclude(self):
        names_qs = await TestObject.objects.values_list('name', flat=True)
        names = list(names_qs)
        self.assertIn('A', names)
        self.assertIn('C', names)

        excl_qs = await TestObject.objects.exclude(name='A').values_list('name', flat=True)
        excl = list(excl_qs)
        self.assertNotIn('A', excl)

    async def test_distinct_and_last(self):
        distinct_qs = await TestObject.objects.values_list('name', flat=True).distinct('name')
        distinct_names = list(distinct_qs)
        # A, C, and E should be present without duplicates
        self.assertCountEqual(distinct_names, ['A', 'C', 'E'])

        # last() without explicit order should use -created
        last_obj = await TestObject.objects.last()
        self.assertIsNotNone(last_obj)
        self.assertIn(last_obj.name, ['A', 'C', 'E'])

    async def test_json_lookups(self):
        # Test numeric filtering
        high_qs = await TestObject.objects.filter(meta__score__gt=5).values_list('name', flat=True)
        high = list(high_qs)
        self.assertCountEqual(high, ['C', 'E'])

        # Test string contains filtering
        alpha_qs = await TestObject.objects.filter(meta__tag__contains='alp').values_list('name', flat=True)
        alpha = list(alpha_qs)
        self.assertCountEqual(alpha, ['C', 'A'])

        # Test exact string matching for type field
        google_qs = await TestObject.objects.filter(meta__type='google').values_list('name', flat=True)
        google_results = list(google_qs)
        self.assertCountEqual(google_results, ['C', 'E'])

        # Test exact string matching for specific type
        dropbox_qs = await TestObject.objects.filter(meta__type__exact='dropbox').values_list('name', flat=True)
        dropbox_results = list(dropbox_qs)
        self.assertCountEqual(dropbox_results, ['A'])

    async def test_meta_type_filtering_comprehensive(self):
        # Test meta__type exact filtering
        google_objects = await TestObject.objects.filter(meta__type="google")
        google_results = [obj.name for obj in google_objects]
        self.assertCountEqual(google_results, ['C', 'E'])
        
        # Test meta__type with case sensitivity
        wrong_case_qs = await TestObject.objects.filter(meta__type="Google")
        wrong_case_results = list(wrong_case_qs)
        self.assertEqual(len(wrong_case_results), 0)

        # Test meta__type with contains
        type_contains_qs = await TestObject.objects.filter(meta__type__contains="goog")
        type_contains_results = [obj.name for obj in type_contains_qs]
        self.assertCountEqual(type_contains_results, ['C', 'E'])

        # Test meta__type case insensitive contains  
        type_icontains_qs = await TestObject.objects.filter(meta__type__icontains="GOOGLE")
        type_icontains_results = [obj.name for obj in type_icontains_qs]
        self.assertCountEqual(type_icontains_results, ['C', 'E'])

        # Test combined filters
        google_alpha_qs = await TestObject.objects.filter(meta__type="google", meta__tag="alpha")
        google_alpha_results = [obj.name for obj in google_alpha_qs]
        self.assertCountEqual(google_alpha_results, ['C'])

        # Test exclude with meta__type
        not_google_qs = await TestObject.objects.exclude(meta__type="google")
        not_google_results = [obj.name for obj in not_google_qs]
        self.assertCountEqual(not_google_results, ['A'])

    async def test_datetime_filtering(self):
        # Test expires__lt filtering (items that have expired)
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        
        # Test the main case that was broken: expires__lt
        expired_qs = await TestObject.objects.filter(expires__lt=now)
        expired_results = [obj.name for obj in expired_qs]
        self.assertCountEqual(expired_results, ['C'])
        
        # Test expires__gt filtering (items that haven't expired yet)  
        not_expired_qs = await TestObject.objects.filter(expires__gt=now)
        not_expired_results = [obj.name for obj in not_expired_qs]
        self.assertCountEqual(not_expired_results, ['A', 'E'])
        
        # Test combined datetime and JSON filtering
        google_not_expired_qs = await TestObject.objects.filter(
            expires__gt=now, 
            meta__type="google"
        )
        google_not_expired_results = [obj.name for obj in google_not_expired_qs]
        self.assertCountEqual(google_not_expired_results, ['E'])

    async def test_datetime_invalid_lookups(self):
        """Test that invalid datetime lookups raise appropriate errors."""
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        
        # Test that string-based lookups raise ValueError for datetime fields
        with self.assertRaises(ValueError) as cm:
            await TestObject.objects.filter(expires__contains="2025")
        self.assertIn("not supported for DateTimeField", str(cm.exception))
        
        with self.assertRaises(ValueError) as cm:
            await TestObject.objects.filter(expires__startswith="2025")
        self.assertIn("not supported for DateTimeField", str(cm.exception))
        
        with self.assertRaises(ValueError) as cm:
            await TestObject.objects.filter(expires__endswith="00:00")
        self.assertIn("not supported for DateTimeField", str(cm.exception))

    async def test_enum_field_filtering(self):
        """Test enum field filtering including __in with enum objects."""
        
        # Test exact enum filtering with enum object
        running_qs = await TestObject.objects.filter(status=TestStatus.RUNNING)
        running_results = [obj.name for obj in running_qs]
        self.assertCountEqual(running_results, ['A'])
        
        # Test exact enum filtering with string value
        completed_qs = await TestObject.objects.filter(status="completed")
        completed_results = [obj.name for obj in completed_qs]
        self.assertCountEqual(completed_results, ['C'])
        
        # Test __in filtering with enum objects (the main issue from your bug report)
        active_statuses = [TestStatus.RUNNING, TestStatus.PENDING]
        active_qs = await TestObject.objects.filter(status__in=active_statuses)
        active_results = [obj.name for obj in active_qs]
        self.assertCountEqual(active_results, ['A', 'E'])
        
        # Test __in filtering with string values
        string_statuses = ["running", "pending"]
        active_string_qs = await TestObject.objects.filter(status__in=string_statuses)
        active_string_results = [obj.name for obj in active_string_qs]
        self.assertCountEqual(active_string_results, ['A', 'E'])
        
        # Test combined enum and other field filtering
        running_google_qs = await TestObject.objects.filter(
            status=TestStatus.RUNNING,
            meta__type="dropbox"
        )
        running_google_results = [obj.name for obj in running_google_qs]
        self.assertCountEqual(running_google_results, ['A'])
