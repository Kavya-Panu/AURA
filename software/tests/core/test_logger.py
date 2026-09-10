"""Tests for core.logger."""
import logging
import tempfile
import unittest
from pathlib import Path

from core.config import LoggingConfig
from core.logger import configure_logging, get_logger, set_debug, shutdown_logging


class TestLogger(unittest.TestCase):
    def tearDown(self):
        shutdown_logging()

    def test_file_logging_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = LoggingConfig(directory=tmp, filename="test.log",
                                debug=False, file_enabled=True)
            configure_logging(cfg)
            log = get_logger("unittest")
            log.info("hello-file")
            for h in logging.getLogger("aura").handlers:
                h.flush()
            content = (Path(tmp) / "test.log").read_text(encoding="utf-8")
            self.assertIn("hello-file", content)
            self.assertIn("aura.unittest", content)
            shutdown_logging()

    def test_child_logger_naming(self):
        log = get_logger("vision")
        self.assertEqual(log.name, "aura.vision")

    def test_reconfigure_does_not_duplicate_handlers(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = LoggingConfig(directory=tmp, file_enabled=True)
            configure_logging(cfg)
            configure_logging(cfg)
            self.assertEqual(len(logging.getLogger("aura").handlers), 2)
            shutdown_logging()

    def test_set_debug_changes_console_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            configure_logging(LoggingConfig(directory=tmp, debug=False))
            set_debug(True)
            console = [h for h in logging.getLogger("aura").handlers
                       if not hasattr(h, "baseFilename")][0]
            self.assertEqual(console.level, logging.DEBUG)
            shutdown_logging()


if __name__ == "__main__":
    unittest.main()
