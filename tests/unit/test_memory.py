"""Tests for memory loading — project file (./AGENT.md) + user file (~/.my-agent/memory/MEMORY.md)."""

from pathlib import Path

from my_agent.agent.memory import (
    DEFAULT_PROJECT_MEMORY_NAME,
    DEFAULT_USER_MEMORY_DIR,
    compose_system_prompt,
    default_user_memory_path,
    load_project_memory,
    load_user_memory,
)


# ---------------- load_project_memory ----------------


def test_load_project_memory_returns_none_when_absent(tmp_path):
    assert load_project_memory(tmp_path) is None


def test_load_project_memory_reads_AGENT_md(tmp_path):
    (tmp_path / DEFAULT_PROJECT_MEMORY_NAME).write_text(
        "# Project rules\n- Always use tabs\n", encoding="utf-8"
    )
    out = load_project_memory(tmp_path)
    assert out is not None
    assert "tabs" in out


def test_load_project_memory_empty_file_returns_none(tmp_path):
    """Empty AGENT.md is treated as 'no memory' — no noise in system prompt."""
    (tmp_path / DEFAULT_PROJECT_MEMORY_NAME).write_text("", encoding="utf-8")
    assert load_project_memory(tmp_path) is None


def test_load_project_memory_strips_whitespace_only(tmp_path):
    (tmp_path / DEFAULT_PROJECT_MEMORY_NAME).write_text("   \n  \n", encoding="utf-8")
    assert load_project_memory(tmp_path) is None


# ---------------- load_user_memory ----------------


def test_load_user_memory_returns_none_when_absent(tmp_path):
    home = tmp_path  # use tmp_path as fake home
    assert load_user_memory(home) is None


def test_load_user_memory_reads_MEMORY_md(tmp_path):
    mem_dir = tmp_path / DEFAULT_USER_MEMORY_DIR
    mem_dir.mkdir(parents=True)
    (mem_dir / "MEMORY.md").write_text("- User prefers terse output\n", encoding="utf-8")

    out = load_user_memory(tmp_path)
    assert out is not None
    assert "terse output" in out


def test_default_user_memory_path_under_home(tmp_path):
    p = default_user_memory_path(tmp_path)
    assert p == tmp_path / DEFAULT_USER_MEMORY_DIR / "MEMORY.md"


# ---------------- compose_system_prompt ----------------


def test_compose_just_base():
    out = compose_system_prompt(base="You are helpful.", project=None, user=None)
    assert out == "You are helpful."


def test_compose_with_project_memory():
    out = compose_system_prompt(
        base="You are helpful.",
        project="# Project\n- rule 1",
        user=None,
    )
    assert "You are helpful." in out
    assert "# Project" in out
    assert "rule 1" in out
    # base must come first
    assert out.index("You are helpful.") < out.index("# Project")


def test_compose_with_user_memory():
    out = compose_system_prompt(
        base="You are helpful.",
        project=None,
        user="- user prefers tabs",
    )
    assert "user prefers tabs" in out


def test_compose_with_both_project_then_user():
    out = compose_system_prompt(
        base="BASE",
        project="PROJECT_MEM",
        user="USER_MEM",
    )
    # ordering: base, then project (more specific to current work), then user
    assert out.index("BASE") < out.index("PROJECT_MEM") < out.index("USER_MEM")


def test_compose_uses_clear_section_markers():
    """Markers help the model know what's instruction vs memory."""
    out = compose_system_prompt(
        base="BASE",
        project="P",
        user="U",
    )
    assert "Project memory" in out or "PROJECT" in out.upper()
    assert "User memory" in out or "USER MEMORY" in out.upper()
