"""
Test cases for URL reverse functionality.

Tests both API-level reverse() and Application-level reverse() methods.
"""
import unittest
from neutronapi import API, Application, Response


class TestAPI(API):
    """Test API with named endpoints for reverse testing."""
    
    resource = "/users"
    
    @API.endpoint("/", methods=["GET"], name="list")
    async def list_users(self, scope, receive, send):
        return await self.response({"users": []})
    
    @API.endpoint("/<int:user_id>", methods=["GET"], name="detail")
    async def get_user(self, scope, receive, send, user_id=None):
        return await self.response({"user_id": user_id})
    
    @API.endpoint("/<int:user_id>/posts/<str:slug>", methods=["GET"], name="user_post")
    async def get_user_post(self, scope, receive, send, user_id=None, slug=None):
        return await self.response({"user_id": user_id, "slug": slug})


class TestReverse(unittest.TestCase):
    """Test URL reverse functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.api = TestAPI()
        self.app = Application(apis={"users": self.api})
    
    def test_api_reverse_simple_route(self):
        """Test API.reverse() with a simple route without parameters."""
        # Should reverse the list endpoint
        url = self.api.reverse("list")
        self.assertEqual(url, "/users/")
    
    def test_api_reverse_route_with_single_parameter(self):
        """Test API.reverse() with a route that has one parameter."""
        # Should reverse the detail endpoint with user_id
        url = self.api.reverse("detail", user_id=123)
        self.assertEqual(url, "/users/123")
    
    def test_api_reverse_route_with_multiple_parameters(self):
        """Test API.reverse() with a route that has multiple parameters."""
        # Should reverse the user_post endpoint with user_id and slug
        url = self.api.reverse("user_post", user_id=456, slug="my-post")
        self.assertEqual(url, "/users/456/posts/my-post")
    
    def test_api_reverse_missing_parameter_raises_error(self):
        """Test API.reverse() raises error when required parameter is missing."""
        with self.assertRaises(ValueError) as cm:
            self.api.reverse("detail")  # Missing user_id
        
        self.assertIn("Missing parameter 'user_id'", str(cm.exception))
    
    def test_api_reverse_nonexistent_route_raises_error(self):
        """Test API.reverse() raises error for non-existent route name."""
        with self.assertRaises(ValueError) as cm:
            self.api.reverse("nonexistent")
        
        self.assertIn("Reverse for 'nonexistent' not found", str(cm.exception))
    
    def test_application_reverse_with_api_name(self):
        """Test Application.reverse() with API name prefix."""
        # Should reverse using "api_name:endpoint_name" format
        url = self.app.reverse("users:list")
        self.assertEqual(url, "/users/")
        
        url = self.app.reverse("users:detail", user_id=789)
        self.assertEqual(url, "/users/789")
    
    def test_application_reverse_missing_api_raises_error(self):
        """Test Application.reverse() raises error for non-existent API."""
        with self.assertRaises(ValueError) as cm:
            self.app.reverse("nonexistent:list")
        
        self.assertIn("API 'nonexistent' not found", str(cm.exception))
    
    def test_application_reverse_invalid_format_raises_error(self):
        """Test Application.reverse() raises error for invalid name format."""
        # Should require "api_name:endpoint_name" format
        with self.assertRaises(ValueError):
            self.app.reverse("invalid_format")
    
    def test_api_reverse_preserves_resource_prefix(self):
        """Test that API.reverse() includes the resource prefix."""
        # Even simple endpoints should include the resource prefix
        url = self.api.reverse("list")
        self.assertTrue(url.startswith("/users"))
    
    def test_api_reverse_handles_different_parameter_types(self):
        """Test API.reverse() works with different parameter types."""
        # Test with string parameter
        url = self.api.reverse("user_post", user_id=123, slug="hello-world")
        self.assertEqual(url, "/users/123/posts/hello-world")
        
        # Test with numeric parameter as string
        url = self.api.reverse("detail", user_id="456")
        self.assertEqual(url, "/users/456")
    
    def test_application_reverse_clarity_example(self):
        """Test to clarify: API 'users' with endpoint 'list' -> 'users:list'."""
        # This clarifies the naming: API name + endpoint name
        url = self.app.reverse("users:list")
        self.assertEqual(url, "/users/")
        
        # API name "users" + endpoint name "detail" = "users:detail"
        url = self.app.reverse("users:detail", user_id=123)
        self.assertEqual(url, "/users/123")


class TestDuplicateRouteNames(unittest.TestCase):
    """Test that duplicate route names are prevented."""
    
    def test_duplicate_route_names_within_same_api_raises_error(self):
        """Test that having duplicate route names within the same API raises an error."""
        
        class UsersAPI(API):
            resource = "/users"
            
            @API.endpoint("/", methods=["GET"], name="list")
            async def list_users(self, scope, receive, send):
                return await self.response({"users": []})
            
            @API.endpoint("/active", methods=["GET"], name="list")  # Duplicate name!
            async def list_active_users(self, scope, receive, send):
                return await self.response({"users": []})
        
        # Should raise error when creating Application with duplicate route names
        with self.assertRaises(ValueError) as cm:
            Application(apis={"users": UsersAPI()})
        
        self.assertIn("Duplicate route name", str(cm.exception))
        self.assertIn("users:list", str(cm.exception))
    
    def test_same_endpoint_names_across_different_apis_is_allowed(self):
        """Test that the same endpoint name across different APIs is allowed."""
        
        class UsersAPI(API):
            resource = "/users"
            
            @API.endpoint("/", methods=["GET"], name="list")
            async def list_users(self, scope, receive, send):
                return await self.response({"users": []})
        
        class PostsAPI(API):
            resource = "/posts"
            
            @API.endpoint("/", methods=["GET"], name="list")  # Same endpoint name, different API
            async def list_posts(self, scope, receive, send):
                return await self.response({"posts": []})
        
        # This should work fine - different APIs can have same endpoint names
        try:
            app = Application(apis={"users": UsersAPI(), "posts": PostsAPI()})
            # Should be able to reverse both
            self.assertEqual(app.reverse("users:list"), "/users/")
            self.assertEqual(app.reverse("posts:list"), "/posts/")
        except ValueError:
            self.fail("Same endpoint names across different APIs should be allowed")
    
    def test_edge_case_manual_duplicate_route_simulation(self):
        """Test the edge case where someone could manually create duplicate route names."""
        
        class UsersAPI1(API):
            resource = "/users"
            
            @API.endpoint("/", methods=["GET"], name="list")
            async def list_users(self, scope, receive, send):
                return await self.response({"users": []})
        
        class UsersAPI2(API):
            resource = "/api/v2/users"  # Different resource
            
            @API.endpoint("/", methods=["GET"], name="list")  
            async def list_users_v2(self, scope, receive, send):
                return await self.response({"users": []})
        
        # Simulate the edge case by manually creating a scenario where
        # two different API instances both get registered with the same key
        # This could happen if someone manipulates the Application after creation
        
        app = Application()
        
        # Manually register both APIs with the same name (simulating the edge case)
        api1 = UsersAPI1() 
        api2 = UsersAPI2()
        
        # First API
        app.apis["users"] = api1
        
        # Now imagine somehow both APIs end up having routes that create the same full name
        # We can test this by temporarily modifying the validation to check this scenario
        
        # For now, let's just verify our current validation works
        try:
            app._validate_unique_route_names()  # Should pass - only one "users" API
        except ValueError:
            self.fail("Single API should not cause validation errors")
        
        # The real edge case would be if we could have two APIs with the same name
        # but that's prevented by Python dict behavior
        # The validation we have protects against duplicate endpoint names within the same API


if __name__ == "__main__":
    unittest.main()