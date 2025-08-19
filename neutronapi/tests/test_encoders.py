import unittest
from datetime import datetime
from enum import Enum
import json

from neutronapi.encoders import CustomJSONEncoder


class E(Enum):
    A = "a"


class TestEncoders(unittest.IsolatedAsyncioTestCase):
    async def test_custom_json_encoder(self):
        data = {"when": datetime(2020, 1, 2, 3, 4, 5), "e": E.A}
        s = json.dumps(data, cls=CustomJSONEncoder)
        self.assertIn("2020-01-02T03:04:05", s)
        self.assertIn("\"a\"", s)

