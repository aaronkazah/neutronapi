import unittest
from datetime import datetime
from decimal import Decimal
from enum import Enum
import json

from neutronapi.encoders import CustomJSONEncoder, json_dumps_bytes, json_loads


class E(Enum):
    A = "a"


class TestEncoders(unittest.IsolatedAsyncioTestCase):
    async def test_custom_json_encoder(self):
        data = {
            "when": datetime(2020, 1, 2, 3, 4, 5),
            "e": E.A,
            "price": Decimal("19.99"),
            "precise": Decimal("0.123456789012345"),
        }
        s = json.dumps(data, cls=CustomJSONEncoder)

        # Test datetime serialization
        self.assertIn("2020-01-02T03:04:05", s)

        # Test enum serialization
        self.assertIn("\"a\"", s)

        # Test decimal serialization (as strings to preserve precision)
        self.assertIn('"19.99"', s)
        self.assertIn('"0.123456789012345"', s)

    async def test_orjson_helpers_round_trip(self):
        data = {"value": Decimal("10.25"), "enum": E.A}

        payload = json_dumps_bytes(data)
        loaded = json_loads(payload)

        self.assertEqual(loaded, {"value": "10.25", "enum": "a"})
