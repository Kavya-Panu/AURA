"""
core/logger.py
==============
Central logging for AURA.

* One root logger ("aura"), every module gets a named child via
  :func:`get_logger` -> log lines show which module spoke.
* Console handler + rotating file handler.
* Debug mode toggled from config (or at runtime with :func:`set_debug`).

Usage::

    from core.logger import configure_logging, get_logger
    configure_logging(cfg.logging)          # once, at startup
    log = get_logger("vision")              # in each module
    log.info("camera opened")
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.config import LoggingConfig

_ROOT_NAME = "aura"
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-18s | %(message)s"
_DATEFMT = "%H:%M:%S"

_configured = False


def configure_logging(cfg: LoggingConfig) -> None:
    """Configure the root AURA logger. Safe to call more than once
    (subsequent calls reconfigure handlers instead of duplicating them)."""
    global _configured
    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(logging.DEBUG)          # handlers filter, root stays open
    root.handlers.clear()
    root.propagate = False

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # Console.
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if cfg.debug else logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file.
    if cfg.file_enabled:
        log_dir = Path(cfg.directory)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / cfg.filename,
            maxBytes=cfg.max_bytes,
            backupCount=cfg.backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(_FORMAT)   # full timestamps in the file
        )
        root.addHandler(file_handler)

    _configured = True


def get_logger(module_name: str) -> logging.Logger:
    """Return a child logger for ``module_name`` (e.g. "event_bus", "vision")."""
    if not _configured:
        # Fallback so imports never crash before configure_logging() runs.
        logging.basicConfig(level=logging.INFO, format=_FORMAT, datefmt=_DATEFMT)
    return logging.getLogger(f"{_ROOT_NAME}.{module_name}")


def set_debug(enabled: bool) -> None:
    """Flip console verbosity at runtime."""
    root = logging.getLogger(_ROOT_NAME)
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, RotatingFileHandler
        ):
            handler.setLevel(logging.DEBUG if enabled else logging.INFO)
