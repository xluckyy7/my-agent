from pathlib import Path

import pytest


@pytest.fixture
def chdir(monkeypatch):
    """Change working directory for the duration of a test.

    Isolates tests from the developer's real .env file in repo root.
    """

    def _chdir(path: Path) -> None:
        monkeypatch.chdir(path)

    return _chdir
