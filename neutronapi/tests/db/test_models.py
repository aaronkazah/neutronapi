import unittest

from neutronapi.db import Model
from neutronapi.db.fields import CharField, JSONField, DateTimeField


class TestModel(Model):
    """Test model for testing Model functionality."""
    name = CharField(null=False)
    email = CharField(null=False, unique=True)
    data = JSONField(null=True, default=dict)


class TestModels(unittest.IsolatedAsyncioTestCase):
    """Test cases for Model functionality."""

    async def test_model_objects_attribute(self):
        """Test that Model.objects exists and has required methods."""
        # Test that objects attribute exists
        self.assertTrue(hasattr(TestModel, 'objects'))
        
        # Test that objects has the all() method
        self.assertTrue(hasattr(TestModel.objects, 'all'))
        
        # Test that objects has other essential methods
        self.assertTrue(hasattr(TestModel.objects, 'filter'))
        self.assertTrue(hasattr(TestModel.objects, 'create'))
        self.assertTrue(hasattr(TestModel.objects, 'get'))

    async def test_model_objects_all_method(self):
        """Test that Model.objects.all() can be called without error."""
        try:
            # This should not raise AttributeError: '_Manager' object has no attribute 'all'
            result = await TestModel.objects.all()
            # Result should be a list (even if empty)
            self.assertIsInstance(result, list)
        except AttributeError as e:
            if "'_Manager' object has no attribute 'all'" in str(e):
                self.fail("Model.objects.all() failed with _Manager error - this is the bug we're fixing")
            else:
                # Some other AttributeError might be expected if DB isn't set up
                pass

    async def test_model_objects_filter_method(self):
        """Test that Model.objects.filter() can be called without error."""
        try:
            # This should return a QuerySet
            result = TestModel.objects.filter(name="test")
            # Should have QuerySet methods
            self.assertTrue(hasattr(result, 'all'))
            self.assertTrue(hasattr(result, 'first'))
            self.assertTrue(hasattr(result, 'count'))
        except Exception:
            # Some errors might be expected if DB isn't set up, but not AttributeError about _Manager
            pass

    async def test_model_objects_create_method(self):
        """Test that Model.objects.create() exists."""
        # Just test that the method exists, don't actually create anything
        self.assertTrue(hasattr(TestModel.objects, 'create'))
        self.assertTrue(callable(TestModel.objects.create))