from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clean_debug_env(monkeypatch):
    """Tests must never inherit MY_AGENT_DEBUG from the developer's shell.

    A stray export in the dev's terminal would otherwise turn on debug
    output during tests and break mock-based assertions (MagicMock chunks
    are not JSON-serializable).
    """
    monkeypatch.delenv("MY_AGENT_DEBUG", raising=False)


@pytest.fixture
def chdir(monkeypatch):
    """Change working directory for the duration of a test.

    Isolates tests from the developer's real .env file in repo root.
    """

    def _chdir(path: Path) -> None:
        monkeypatch.chdir(path)

    return _chdir
