"""
Tests for Application routing functionality
"""
import asyncio
from neutronapi.base import API
from neutronapi.application import Application


class TestApplicationRouting:
    """Test routing behavior in Application class"""
    
    def test_dict_syntax_api_registration(self):
        """Test that APIs are registered correctly with dict syntax"""
        
        class HelloAPI(API):
            resource = "/hello"
            
            @API.endpoint("/", methods=["GET"])
            async def get(self, scope, receive, send, **kwargs):
                return await self.response({"message": "hello"})
        
        # Old dict syntax (backwards compatible)
        app = Application(apis={"/hello": HelloAPI()})
        
        # Test that the API is registered
        assert "/hello" in app.apis
        assert isinstance(app.apis["/hello"], HelloAPI)
    
    def test_array_syntax_api_registration(self):
        """Test that APIs are registered correctly with array syntax"""
        
        class HelloAPI(API):
            resource = "/hello"
            
            @API.endpoint("/", methods=["GET"])
            async def get(self, scope, receive, send, **kwargs):
                return await self.response({"message": "hello"})
        
        class UsersAPI(API):
            resource = "/users"
            
            @API.endpoint("/", methods=["GET"])
            async def get(self, scope, receive, send, **kwargs):
                return await self.response({"users": []})
        
        # Array syntax with named parameter
        app = Application(apis=[HelloAPI(), UsersAPI()])
        
        # Test that APIs are registered using their resource paths
        assert "/hello" in app.apis
        assert "/users" in app.apis
        assert isinstance(app.apis["/hello"], HelloAPI)
        assert isinstance(app.apis["/users"], UsersAPI)
    
    def test_api_registration_order(self):
        """Test that APIs are registered in the correct order"""
        
        class API1(API):
            resource = "/first"
            
            @API.endpoint("/", methods=["GET"])
            async def get(self, scope, receive, send, **kwargs):
                return await self.response({"order": 1})
        
        class API2(API):
            resource = "/second"
            
            @API.endpoint("/", methods=["GET"])
            async def get(self, scope, receive, send, **kwargs):
                return await self.response({"order": 2})
        
        class API3(API):
            resource = "/third"
            
            @API.endpoint("/", methods=["GET"])
            async def get(self, scope, receive, send, **kwargs):
                return await self.response({"order": 3})
        
        app = Application(apis=[API1(), API2(), API3()])
        
        # Test that order is preserved
        api_paths = list(app.apis.keys())
        assert api_paths == ["/first", "/second", "/third"]
    
    def test_empty_apis_list(self):
        """Test that empty APIs list works"""
        app = Application(apis=[])
        assert len(app.apis) == 0
    
    async def test_exact_path_matching(self):
        """Test that exact path matches work"""
        
        class TestAPI(API):
            resource = "/test"
            
            @API.endpoint("/", methods=["GET"])
            async def get(self, scope, receive, send, **kwargs):
                return await self.response({"matched": True})
        
        app = Application(apis=[TestAPI()])
        
        responses = []
        
        async def receive():
            return {"type": "http.request", "body": b""}
        
        async def send(response):
            responses.append(response)
        
        scope = {
            "type": "http",
            "method": "GET", 
            "path": "/test/",  # Note: API endpoint is "/" which gets prepended with resource
            "query_string": b"",
            "headers": []
        }
        
        await app(scope, receive, send)
        
        # Should find a successful response (not 404)
        assert any(resp.get("status") != 404 for resp in responses if "status" in resp)
    
    async def test_prefix_path_matching(self):
        """Test that prefix path matching works for sub-routes"""
        
        class APIV1(API):
            resource = "/api/v1"
            
            @API.endpoint("/users", methods=["GET"])
            async def get_users(self, scope, receive, send, **kwargs):
                return await self.response({"users": []})
        
        app = Application(apis=[APIV1()])
        
        responses = []
        
        async def receive():
            return {"type": "http.request", "body": b""}
        
        async def send(response):
            responses.append(response)
        
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/users", 
            "query_string": b"",
            "headers": []
        }
        
        await app(scope, receive, send)
        
        # Should find a successful response (not 404)
        assert any(resp.get("status") != 404 for resp in responses if "status" in resp)
    
    async def test_404_for_unmatched_paths(self):
        """Test that unmatched paths return 404"""
        
        class TestAPI(API):
            resource = "/test"
            
            @API.endpoint("/", methods=["GET"])
            async def get(self, scope, receive, send, **kwargs):
                return await self.response({"matched": True})
        
        app = Application(apis=[TestAPI()])
        
        responses = []
        
        async def receive():
            return {"type": "http.request", "body": b""}
        
        async def send(response):
            responses.append(response)
        
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/nonexistent",
            "query_string": b"", 
            "headers": []
        }
        
        await app(scope, receive, send)
        
        # Should return 404
        assert any(resp.get("status") == 404 for resp in responses if "status" in resp)
    
    def test_redundant_resource_declaration(self):
        """Test case highlighting the redundancy of declaring resource twice"""
        
        class RedundantAPI(API):
            # This is redundant with the key in Application apis dict
            resource = "/redundant"  
            
            @API.endpoint("/", methods=["GET"])
            async def get(self, scope, receive, send, **kwargs):
                return await self.response({"message": "redundant"})
        
        # Having to specify the path twice is redundant:
        # 1. In the class: resource = "/redundant"
        # 2. In the Application: {"/redundant": RedundantAPI()}
        app = Application(apis={"/redundant": RedundantAPI()})
        
        # This works but shows the redundancy
        assert "/redundant" in app.apis
        assert app.apis["/redundant"].resource == "/redundant"
        
        # TODO: Consider making this more like FastAPI where you just do:
        # app.include_router(RedundantAPI(), prefix="/redundant")