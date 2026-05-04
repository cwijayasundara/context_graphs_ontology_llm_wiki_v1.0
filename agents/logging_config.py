"""Shared logging setup for CLI scripts and agent tools."""
from __future__ import annotations

import logging
import os
import sys

ROOT_LOGGER = "context_graphs"


def configure_logging(name: str = ROOT_LOGGER) -> logging.Logger:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger = logging.getLogger(ROOT_LOGGER)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s - %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    child = logging.getLogger(name)
    child.setLevel(level)
    return child


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")
