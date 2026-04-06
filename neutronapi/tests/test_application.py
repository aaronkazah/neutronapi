import unittest

from neutronapi.base import API
from neutronapi.application import Application
from neutronapi.middleware.cors import CorsMiddleware


class PingAPI(API):
    name = "ping"
    resource = ""

    @API.endpoint("/ping", methods=["GET"], name="ping")
    async def ping(self, scope, receive, send, **kwargs):
        return await self.response({"ok": True, "path": scope.get("path")})


class DefaultRootAPI(API):
    name = "default_root"
    resource = ""

    @API.endpoint("/ping", methods=["GET"], name="ping")
    async def ping(self, scope, receive, send, **kwargs):
        return await self.response({"api": "default"})


class StorageRootAPI(API):
    name = "storage_root"
    resource = ""
    hosts = ["storage.example.com"]
    excluded_path_prefixes = ["/v1/"]

    @API.endpoint("/ping", methods=["GET"], name="ping")
    async def ping(self, scope, receive, send, **kwargs):
        return await self.response({"api": "storage"})


class ControlPlaneAPI(API):
    name = "control_plane"
    resource = "/v1/storage"

    @API.endpoint("/backends", methods=["GET"], name="backends")
    async def list_backends(self, scope, receive, send, **kwargs):
        return await self.response({"api": "control"})


async def call_asgi(app, scope, body: bytes = b""):
    messages = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


class PassThroughMiddleware:
    def __init__(self):
        self.app = None
        self.registry = None

    async def __call__(self, scope, receive, send, **kwargs):
        await self.app(scope, receive, send, **kwargs)


class TestAPIAndApplication(unittest.IsolatedAsyncioTestCase):
    async def test_api_reverse(self):
        api = PingAPI()
        url = api.reverse("ping")
        self.assertEqual(url, "/ping")

    async def test_application_basic_request(self):
        app = Application({"ping": PingAPI()})

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/ping",
            "headers": [],
        }

        messages = await call_asgi(app, scope)
        # Expect start + body
        self.assertEqual(messages[0]["type"], "http.response.start")
        self.assertEqual(messages[0]["status"], 200)
        self.assertEqual(messages[1]["type"], "http.response.body")

    async def test_application_keeps_allow_all_cors_with_custom_middleware(self):
        app = Application(
            {"ping": PingAPI()},
            cors_allow_all=True,
            middlewares=[PassThroughMiddleware()],
        )

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/ping",
            "headers": [
                (b"host", b"api.example.com"),
                (b"origin", b"https://evil.example"),
            ],
        }

        messages = await call_asgi(app, scope)
        headers = dict(messages[0]["headers"])
        self.assertEqual(
            headers[b"Access-Control-Allow-Origin"],
            b"https://evil.example",
        )
        self.assertEqual(headers[b"Vary"], b"Origin")

    def test_application_rejects_double_cors_configuration(self):
        with self.assertRaises(ValueError) as ctx:
            Application(
                {"ping": PingAPI()},
                cors_allow_all=True,
                middlewares=[
                    CorsMiddleware(allowed_origins=["https://app.example.com"])
                ],
            )

        self.assertIn("Ambiguous CORS configuration", str(ctx.exception))

    async def test_host_scoped_root_api_wins_on_matching_host(self):
        app = Application(
            apis=[DefaultRootAPI(), StorageRootAPI(), ControlPlaneAPI()],
        )

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/ping",
            "headers": [(b"host", b"storage.example.com")],
        }

        messages = await call_asgi(app, scope)

        self.assertEqual(messages[0]["status"], 200)
        self.assertIn(b'"api": "storage"', messages[1]["body"])

    async def test_host_scoped_root_api_is_ignored_on_other_hosts(self):
        app = Application(
            apis=[DefaultRootAPI(), StorageRootAPI(), ControlPlaneAPI()],
        )

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/ping",
            "headers": [(b"host", b"api.example.com")],
        }

        messages = await call_asgi(app, scope)

        self.assertEqual(messages[0]["status"], 200)
        self.assertIn(b'"api": "default"', messages[1]["body"])

    async def test_host_scoped_root_api_does_not_expose_control_plane_paths(self):
        app = Application(
            apis=[StorageRootAPI(), ControlPlaneAPI()],
        )

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/storage/backends",
            "headers": [(b"host", b"storage.example.com")],
        }

        messages = await call_asgi(app, scope)

        self.assertEqual(messages[0]["status"], 404)

class MockUtil:
    def __init__(self, util_id):
        self.id = util_id
        self.value = f"util_{util_id}"


class TestApplicationRegistry(unittest.IsolatedAsyncioTestCase):
    def test_registry_parameter(self):
        """Test registry parameter accepts namespace:name format"""
        app = Application(
            registry={
                'utils:logger': MockUtil('logger'),
                'services:email': MockUtil('email'),
                'modules:auth': {'auth_enabled': True}
            }
        )
        
        self.assertEqual(len(app.registry), 3)
        self.assertIn('utils:logger', app.registry)
        self.assertIn('services:email', app.registry)
        self.assertIn('modules:auth', app.registry)
        
        # Test access
        logger = app.registry.get('utils:logger')
        self.assertEqual(logger.value, 'util_logger')
    
    def test_registry_validation_invalid_format(self):
        """Test registry key validation rejects invalid formats"""
        with self.assertRaises(ValueError) as ctx:
            Application(registry={'invalid_key': 'value'})
        self.assertIn('namespace:name', str(ctx.exception))
    
    def test_registry_validation_empty_parts(self):
        """Test registry key validation rejects empty namespace or name"""
        with self.assertRaises(ValueError) as ctx:
            Application(registry={':empty_namespace': 'value'})
        self.assertIn('both namespace and name', str(ctx.exception))
        
        with self.assertRaises(ValueError) as ctx:
            Application(registry={'empty_name:': 'value'})
        self.assertIn('both namespace and name', str(ctx.exception))
    
    def test_registry_validation_invalid_characters(self):
        """Test registry key validation rejects invalid characters"""
        with self.assertRaises(ValueError) as ctx:
            Application(registry={'utils:my-logger': 'value'})
        self.assertIn('invalid characters', str(ctx.exception))
    
    def test_registry_duplicate_keys(self):
        """Test registry prevents duplicate keys via register() method"""
        app = Application(registry={'utils:logger': MockUtil('logger1')})
        
        with self.assertRaises(ValueError) as ctx:
            app.register('utils:logger', MockUtil('logger2'))
        self.assertIn('already exists', str(ctx.exception))
    
    def test_register_method(self):
        """Test dynamic registration via register() method"""
        app = Application()
        
        # Test successful registration
        app.register('utils:logger', MockUtil('logger'))
        self.assertIn('utils:logger', app.registry)
        
        # Test duplicate registration fails
        with self.assertRaises(ValueError) as ctx:
            app.register('utils:logger', MockUtil('logger2'))
        self.assertIn('already exists', str(ctx.exception))
    
    def test_register_method_validation(self):
        """Test register() method validates keys"""
        app = Application()
        
        with self.assertRaises(ValueError) as ctx:
            app.register('invalid_key', 'value')
        self.assertIn('namespace:name', str(ctx.exception))
    
    def test_api_gets_registry(self):
        """Test APIs receive registry attribute"""
        api = PingAPI()
        app = Application(
            apis=[api],
            registry={'utils:logger': MockUtil('logger')}
        )
        
        self.assertTrue(hasattr(api, 'registry'))
        self.assertIn('utils:logger', api.registry)
    
    def test_register_updates_existing_apis(self):
        """Test register() updates registry in existing APIs"""
        api = PingAPI()
        app = Application(apis=[api])
        
        # Initially empty
        self.assertEqual(len(api.registry), 0)
        
        # Register new item
        app.register('utils:cache', MockUtil('cache'))
        
        # API should get updated registry
        self.assertIn('utils:cache', api.registry)
