from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

from logging_config import configure_logging, get_logger  # noqa: E402


def test_configure_logging_sets_level_and_returns_named_logger(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    logger = configure_logging("context_graphs.test")

    assert logger.level == logging.DEBUG
    assert get_logger("child").name == "context_graphs.child"
