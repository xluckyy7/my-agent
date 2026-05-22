"""Centralized logging setup for my-agent.

Two entry points (cli/main.app and web/server.serve) call `setup_logging()`
exactly once at startup. All other modules use the standard pattern:

    import logging
    logger = logging.getLogger(__name__)
    logger.info("...")

This module owns the root logger config so callers don't fight over it.

Level resolution (highest priority wins):
    explicit `setup_logging(level=...)` arg
  > MY_AGENT_LOG_LEVEL env (e.g. "DEBUG")
  > MY_AGENT_DEBUG=1 env (forces DEBUG, shortcut for backward compat)
  > INFO (default)

The handler writes to stderr with a short formatter:

    INFO     my_agent.plugins.langfuse_plugin: initialized (host=...)
    WARNING  my_agent.web.sessions: skipping corrupt file broken.json: ...

setup_logging() is idempotent — repeated calls reconfigure level cleanly
without stacking handlers.
"""

import logging
import os
import sys
from typing import Optional, Union

_HANDLER_TAG = "_my_agent_handler"
_DEFAULT_FORMAT = "%(levelname)-7s %(name)s: %(message)s"


def _resolve_level(level: Optional[Union[int, str]]) -> int:
    if level is not None:
        if isinstance(level, str):
            return logging.getLevelName(level.upper())  # type: ignore[return-value]
        return level
    env_level = os.environ.get("MY_AGENT_LOG_LEVEL")
    if env_level:
        return logging.getLevelName(env_level.upper())  # type: ignore[return-value]
    if os.environ.get("MY_AGENT_DEBUG", "").lower() not in ("", "0", "false", "no"):
        return logging.DEBUG
    return logging.INFO


def setup_logging(level: Optional[Union[int, str]] = None) -> None:
    """Configure the root logger for my-agent. Idempotent.

    Attaches one StreamHandler(stderr) tagged so subsequent calls replace it
    instead of stacking. Sets level per the resolution order above.
    """
    resolved = _resolve_level(level)
    root = logging.getLogger()
    root.setLevel(resolved)

    # Remove our previously-installed handler (if any) so re-call is clean.
    for h in list(root.handlers):
        if getattr(h, "_tag", None) == _HANDLER_TAG:
            root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(resolved)
    handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))
    handler._tag = _HANDLER_TAG  # type: ignore[attr-defined]
    root.addHandler(handler)
