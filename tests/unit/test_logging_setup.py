"""Tests for the centralized logging setup."""

import logging

from my_agent._logging import setup_logging


def _our_handlers(root):
    return [h for h in root.handlers if getattr(h, "_tag", None) == "_my_agent_handler"]


def test_setup_logging_attaches_exactly_one_handler():
    root = logging.getLogger()
    before = len(_our_handlers(root))
    setup_logging()
    after = len(_our_handlers(root))
    assert after - before == 1 or after == 1


def test_setup_logging_is_idempotent():
    """Calling repeatedly must replace, not stack, our handler."""
    setup_logging()
    setup_logging()
    setup_logging()
    root = logging.getLogger()
    assert len(_our_handlers(root)) == 1


def test_explicit_level_wins(monkeypatch):
    monkeypatch.setenv("MY_AGENT_LOG_LEVEL", "ERROR")
    setup_logging(level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_env_log_level_string(monkeypatch):
    monkeypatch.setenv("MY_AGENT_LOG_LEVEL", "WARNING")
    monkeypatch.delenv("MY_AGENT_DEBUG", raising=False)
    setup_logging()
    assert logging.getLogger().level == logging.WARNING


def test_debug_env_forces_debug(monkeypatch):
    monkeypatch.delenv("MY_AGENT_LOG_LEVEL", raising=False)
    monkeypatch.setenv("MY_AGENT_DEBUG", "1")
    setup_logging()
    assert logging.getLogger().level == logging.DEBUG


def test_default_is_info(monkeypatch):
    monkeypatch.delenv("MY_AGENT_LOG_LEVEL", raising=False)
    monkeypatch.delenv("MY_AGENT_DEBUG", raising=False)
    setup_logging()
    assert logging.getLogger().level == logging.INFO


def test_debug_falsy_values(monkeypatch):
    """MY_AGENT_DEBUG=0/false/no should NOT enable debug."""
    monkeypatch.delenv("MY_AGENT_LOG_LEVEL", raising=False)
    for val in ["", "0", "false", "FALSE", "no"]:
        monkeypatch.setenv("MY_AGENT_DEBUG", val)
        setup_logging()
        assert logging.getLogger().level == logging.INFO, (
            f"MY_AGENT_DEBUG={val!r} unexpectedly enabled DEBUG"
        )
