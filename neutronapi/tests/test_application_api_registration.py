import unittest
from neutronapi.application import Application
from neutronapi.base import API


class MockAPI(API):
    """Mock API for testing."""
    def __init__(self, name=None, resource=None):
        self.name = name
        self.resource = resource or "/v1/test"
        self.routes = {}

    def reverse(self, endpoint_name, **kwargs):
        """Mock reverse method."""
        name = getattr(self, 'name', 'unknown')
        return f"/{name}/{endpoint_name}"


class TestApplicationAPIRegistration(unittest.TestCase):
    """Test Application API registration and reverse lookup functionality."""

    def test_list_apis_with_name_attribute(self):
        """Test that APIs with name attributes are registered correctly."""
        auth_api = MockAPI(name="auth", resource="/v1/auth")
        users_api = MockAPI(name="users", resource="/v1/users")
        
        app = Application(apis=[auth_api, users_api])
        
        # Check that APIs are registered with their name as key
        self.assertIn("auth", app.apis)
        self.assertIn("users", app.apis)
        self.assertEqual(app.apis["auth"], auth_api)
        self.assertEqual(app.apis["users"], users_api)

    def test_reverse_lookup_with_api_name(self):
        """Test that reverse lookup works with API name."""
        auth_api = MockAPI(name="auth", resource="/v1/auth")
        app = Application(apis=[auth_api])
        
        # Test reverse lookup
        result = app.reverse("auth:login")
        self.assertEqual(result, "/auth/login")

    def test_missing_name_attribute_raises_error(self):
        """Test that missing name attribute raises ValueError."""
        api_without_name = MockAPI(resource="/v1/test")  # No name provided
        
        with self.assertRaises(ValueError) as context:
            Application(apis=[api_without_name])
        
        self.assertIn("must have a 'name' attribute", str(context.exception))

    def test_empty_name_attribute_raises_error(self):
        """Test that empty name attribute raises ValueError."""
        api_with_empty_name = MockAPI(name="", resource="/v1/test")
        
        with self.assertRaises(ValueError) as context:
            Application(apis=[api_with_empty_name])
        
        self.assertIn("must have a 'name' attribute", str(context.exception))

    def test_none_name_attribute_raises_error(self):
        """Test that None name attribute raises ValueError."""
        api_with_none_name = MockAPI(name=None, resource="/v1/test")
        
        with self.assertRaises(ValueError) as context:
            Application(apis=[api_with_none_name])
        
        self.assertIn("must have a 'name' attribute", str(context.exception))

    def test_dict_apis_still_work(self):
        """Test that dict-based API registration still works."""
        auth_api = MockAPI(resource="/v1/auth")
        users_api = MockAPI(resource="/v1/users")
        
        app = Application(apis={
            "auth": auth_api,
            "users": users_api
        })
        
        # Check that APIs are registered with provided keys
        self.assertIn("auth", app.apis)
        self.assertIn("users", app.apis)
        self.assertEqual(app.apis["auth"], auth_api)
        self.assertEqual(app.apis["users"], users_api)

    def test_reverse_lookup_with_dict_apis(self):
        """Test reverse lookup works with dict-based registration."""
        auth_api = MockAPI(name="auth", resource="/v1/auth")  # Set name for consistent behavior
        app = Application(apis={"auth": auth_api})
        
        result = app.reverse("auth:login")
        self.assertEqual(result, "/auth/login")

    def test_api_not_found_error(self):
        """Test that reverse lookup raises error for unknown API."""
        auth_api = MockAPI(name="auth", resource="/v1/auth")
        app = Application(apis=[auth_api])
        
        with self.assertRaises(ValueError) as context:
            app.reverse("unknown:endpoint")
        
        self.assertIn("API 'unknown' not found", str(context.exception))

    def test_invalid_route_name_format(self):
        """Test that invalid route name format raises error."""
        auth_api = MockAPI(name="auth", resource="/v1/auth")
        app = Application(apis=[auth_api])
        
        with self.assertRaises(ValueError) as context:
            app.reverse("invalid_format")
        
        self.assertIn("must be in format 'api_name:endpoint_name'", str(context.exception))


if __name__ == '__main__':
    unittest.main()