import os
import re
import unittest

from neutronapi.db import setup_databases, get_databases
from neutronapi.db.models import Model
from neutronapi.db.fields import CharField


class AutoPKModel(Model):
    name = CharField(null=True)


class TestAutoPrimaryKey(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Force an in-memory SQLite DB for deterministic tests
        os.environ['TESTING'] = '1'
        cfg = {
            'default': {
                'ENGINE': 'aiosqlite',
                'NAME': ':memory:',
            }
        }
        setup_databases(cfg)
        conn = await get_databases().get_connection('default')
        self.provider = conn.provider

        # Create the table backing AutoPKModel
        app_label, table_base = AutoPKModel._get_parsed_table_name()
        await self.provider.create_table(app_label, table_base, list(AutoPKModel._neutronapi_fields_.items()))

    async def asyncTearDown(self):
        try:
            app_label, table_base = AutoPKModel._get_parsed_table_name()
            await self.provider.drop_table(app_label, table_base)
        except Exception:
            pass

    async def test_auto_generates_id_when_missing(self):
        obj = await AutoPKModel.objects.create(name="alpha")
        self.assertIsInstance(obj.id, str)
        self.assertTrue(len(obj.id) > 0)
        # Accept either UUIDv7 (36, with dashes) or ULID (26, Crockford base32)
        is_uuid7 = bool(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", obj.id))
        is_ulid = len(obj.id) == 26 and obj.id.isalnum()
        self.assertTrue(is_uuid7 or is_ulid, f"Unexpected ID format: {obj.id}")

    async def test_respects_user_provided_id(self):
        custom_id = "TESTCUSTOMID1234567890ABCD"  # 26 chars
        obj = await AutoPKModel.objects.create(id=custom_id, name="beta")
        self.assertEqual(obj.id, custom_id)

