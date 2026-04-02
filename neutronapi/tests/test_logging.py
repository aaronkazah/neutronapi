import logging
import unittest
from io import StringIO

from neutronapi.logging import EventFormatter, configure_logging, get_logger, log_event


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


class TestEventFormatter(unittest.TestCase):
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
        formatter = EventFormatter()
        output = formatter.format(record)
        self.assertIn('"event"', output)
        self.assertIn("test message", output)
        self.assertIn('"ts"', output)

    def test_log_event(self):
        root = logging.getLogger("neutronapi")
        root.handlers.clear()
        buf = StringIO()
        configure_logging(level="INFO", fmt="json", stream=buf)
        logger = get_logger("structured")
        log_event(logger, logging.INFO, "request.completed", request_id="req_123", status=200)
        output = buf.getvalue()
        self.assertIn('"request.completed"', output)
        self.assertIn('"request_id"', output)
