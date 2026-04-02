import logging
import unittest
from io import StringIO

from neutronapi.logging import get_logger, configure_logging, JSONFormatter


class TestGetLogger(unittest.TestCase):
    def test_prefixes_name(self):
        logger = get_logger("mymodule")
        self.assertEqual(logger.name, "neutronapi.mymodule")

    def test_already_prefixed(self):
        logger = get_logger("neutronapi.db")
        self.assertEqual(logger.name, "neutronapi.db")


class TestConfigureLogging(unittest.TestCase):
    def setUp(self):
        # Remove any handlers added by previous tests
        root = logging.getLogger("neutronapi")
        root.handlers.clear()

    def tearDown(self):
        root = logging.getLogger("neutronapi")
        root.handlers.clear()

    def test_text_format(self):
        buf = StringIO()
        configure_logging(level="DEBUG", fmt="text", stream=buf)
        logger = get_logger("test_text")
        logger.info("hello world")
        output = buf.getvalue()
        self.assertIn("hello world", output)
        self.assertIn("INFO", output)

    def test_json_format(self):
        buf = StringIO()
        configure_logging(level="DEBUG", fmt="json", stream=buf)
        logger = get_logger("test_json")
        logger.warning("structured")
        output = buf.getvalue()
        self.assertIn('"level"', output)
        self.assertIn('"WARNING"', output)
        self.assertIn('"structured"', output)

    def test_idempotent(self):
        configure_logging(level="DEBUG", fmt="text")
        configure_logging(level="DEBUG", fmt="text")
        root = logging.getLogger("neutronapi")
        self.assertEqual(len(root.handlers), 1)


class TestJSONFormatter(unittest.TestCase):
    def test_format_basic(self):
        record = logging.LogRecord(
            name="neutronapi.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        formatter = JSONFormatter()
        output = formatter.format(record)
        self.assertIn('"msg"', output)
        self.assertIn("test message", output)
        self.assertIn('"ts"', output)
