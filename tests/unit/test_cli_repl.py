import io
from unittest.mock import MagicMock

import pytest

from my_agent.agent.conversation import Conversation
from my_agent.cli.repl import (
    COMMANDS,
    Repl,
    cmd_compact,
    cmd_help,
    cmd_load,
    cmd_memory,
    cmd_quit,
    cmd_reset,
    cmd_save,
    cmd_tokens,
)


def _make_repl(out=None, err=None):
    loop = MagicMock()
    conv = Conversation(system="be helpful")
    return Repl(
        loop=loop,
        conv=conv,
        out=out or io.StringIO(),
        err=err or io.StringIO(),
    )


# ---------------- command dispatch ----------------


def test_quit_sets_flag():
    repl = _make_repl()
    cmd_quit(repl, "")
    assert repl._quit is True


def test_reset_replaces_conversation_keeps_system():
    repl = _make_repl()
    repl.conv.append_user("hi")
    assert len(repl.conv.messages) == 2

    cmd_reset(repl, "")
    assert len(repl.conv.messages) == 1
    assert repl.conv.messages[0].role == "system"
    assert repl.conv.messages[0].content == "be helpful"


def test_save_writes_file(tmp_path):
    out = io.StringIO()
    repl = _make_repl(out=out)
    repl.conv.append_user("hi")
    repl.conv.append_assistant(content="hello")

    target = tmp_path / "x.json"
    cmd_save(repl, str(target))
    assert target.exists()
    assert "hi" in target.read_text()


def test_save_requires_path():
    err = io.StringIO()
    repl = _make_repl(err=err)
    cmd_save(repl, "")
    assert "path" in err.getvalue().lower() or "usage" in err.getvalue().lower()


def test_load_restores_conversation(tmp_path):
    repl = _make_repl()
    target = tmp_path / "x.json"
    target.write_text(
        '{"messages": ['
        '{"role": "system", "content": "loaded sys"},'
        '{"role": "user", "content": "hello-from-disk"}'
        ']}',
        encoding="utf-8",
    )

    cmd_load(repl, str(target))
    assert repl.conv.system == "loaded sys"
    assert repl.conv.messages[1].content == "hello-from-disk"


def test_load_bad_file_prints_error(tmp_path):
    err = io.StringIO()
    repl = _make_repl(err=err)
    cmd_load(repl, str(tmp_path / "nope.json"))
    assert err.getvalue()  # something got printed


def test_help_lists_commands():
    out = io.StringIO()
    repl = _make_repl(out=out)
    cmd_help(repl, "")
    text = out.getvalue()
    for cmd in ["quit", "reset", "save", "load", "help"]:
        assert cmd in text


def test_commands_table_has_aliases():
    for alias in ["q", "exit"]:
        assert alias in COMMANDS
    assert COMMANDS["q"] is cmd_quit
    assert COMMANDS["exit"] is cmd_quit


# ---------------- Repl.handle_input ----------------


def test_handle_input_slash_dispatches_command():
    repl = _make_repl()
    repl.handle_input("/quit")
    assert repl._quit is True
    repl.loop.run_turn_stream.assert_not_called()


def test_handle_input_unknown_command_prints_error():
    err = io.StringIO()
    repl = _make_repl(err=err)
    repl.handle_input("/xyz")
    assert "unknown" in err.getvalue().lower()
    repl.loop.run_turn_stream.assert_not_called()


def test_handle_input_plain_text_calls_loop():
    repl = _make_repl()
    repl.loop.run_turn_stream.return_value = iter([])
    repl.handle_input("hello")
    repl.loop.run_turn_stream.assert_called_once_with(repl.conv, "hello")


def test_handle_input_empty_is_noop():
    repl = _make_repl()
    repl.handle_input("")
    repl.handle_input("   ")
    repl.loop.run_turn_stream.assert_not_called()


def test_handle_input_keyboard_interrupt_does_not_exit():
    """ctrl-c during a turn should NOT set _quit."""
    err = io.StringIO()
    repl = _make_repl(err=err)
    repl.loop.run_turn_stream.side_effect = KeyboardInterrupt()
    repl.handle_input("anything")
    assert repl._quit is False
    assert "interrupt" in err.getvalue().lower()


# ---------------- ctrl-c at prompt: double-tap to exit ----------------


def test_single_sigint_does_not_exit():
    repl = _make_repl()
    assert repl._should_exit_on_sigint() is False


def test_double_sigint_within_window_exits():
    """Two ctrl-c presses within SIGINT_EXIT_WINDOW seconds → exit."""
    repl = _make_repl()
    repl._should_exit_on_sigint()  # first press
    # second press immediately after → should exit
    assert repl._should_exit_on_sigint() is True


def test_double_sigint_outside_window_does_not_exit(monkeypatch):
    """If the two presses are too far apart, second press only shows hint again."""
    import my_agent.cli.repl as repl_mod

    times = iter([100.0, 200.0])  # 100s apart, way outside 2s window
    monkeypatch.setattr(repl_mod.time, "monotonic", lambda: next(times))

    repl = _make_repl()
    assert repl._should_exit_on_sigint() is False  # first press at t=100
    assert repl._should_exit_on_sigint() is False  # second press at t=200 (100s later)


def test_run_two_ctrl_c_exits(monkeypatch):
    """End-to-end via input() mock: two ctrl-c presses exit the run() loop."""
    repl = _make_repl()
    presses = iter([KeyboardInterrupt(), KeyboardInterrupt()])

    def fake_input(prompt):
        raise next(presses)

    monkeypatch.setattr("builtins.input", fake_input)
    assert repl.run() == 0


# ---------------- /tokens and /compact ----------------


def _make_repl_with_cm(out=None, err=None):
    """Repl with a mock ContextManager attached to its loop."""
    repl = _make_repl(out=out, err=err)
    cm = MagicMock()
    cm.budget = 8000
    cm.total_tokens.return_value = 1234
    repl.loop.context_mgr = cm
    return repl, cm


def test_tokens_reports_count_and_budget():
    out = io.StringIO()
    repl, cm = _make_repl_with_cm(out=out)
    cmd_tokens(repl, "")
    text = out.getvalue()
    assert "1234" in text
    assert "8000" in text
    assert "%" in text


def test_tokens_without_context_mgr_errors():
    err = io.StringIO()
    repl = _make_repl(err=err)
    repl.loop.context_mgr = None
    cmd_tokens(repl, "")
    assert "no ContextManager" in err.getvalue() or "no" in err.getvalue().lower()


def test_compact_force_compacts_and_reports_savings():
    out = io.StringIO()
    repl, cm = _make_repl_with_cm(out=out)
    # before=1234, after=400 → 67% saved
    cm.total_tokens.side_effect = [1234, 400]
    cm.force_compact.return_value = True

    cmd_compact(repl, "")
    text = out.getvalue()
    assert "1234" in text
    assert "400" in text
    cm.force_compact.assert_called_once_with(repl.conv)


def test_compact_nothing_to_compact_message():
    out = io.StringIO()
    repl, cm = _make_repl_with_cm(out=out)
    cm.total_tokens.return_value = 100
    cm.force_compact.return_value = False
    cmd_compact(repl, "")
    assert "nothing to compact" in out.getvalue().lower()


def test_compact_without_context_mgr_errors():
    err = io.StringIO()
    repl = _make_repl(err=err)
    repl.loop.context_mgr = None
    cmd_compact(repl, "")
    assert "no" in err.getvalue().lower()


def test_help_lists_new_commands():
    out = io.StringIO()
    repl = _make_repl(out=out)
    cmd_help(repl, "")
    text = out.getvalue()
    assert "/tokens" in text
    assert "/compact" in text


def test_commands_table_has_tokens_and_compact():
    assert "tokens" in COMMANDS
    assert "compact" in COMMANDS
    assert COMMANDS["tokens"] is cmd_tokens
    assert COMMANDS["compact"] is cmd_compact


# ---------------- /memory ----------------


def test_memory_list_shows_existing_user_memory(tmp_path, monkeypatch):
    """`/memory` (no args) prints current user memory content."""
    monkeypatch.setenv("HOME", str(tmp_path))
    mem_path = tmp_path / ".my-agent" / "memory" / "MEMORY.md"
    mem_path.parent.mkdir(parents=True)
    mem_path.write_text("- 2026-05-21: user likes terse output\n", encoding="utf-8")

    out = io.StringIO()
    repl = _make_repl(out=out)
    cmd_memory(repl, "")
    assert "terse output" in out.getvalue()


def test_memory_list_says_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    out = io.StringIO()
    repl = _make_repl(out=out)
    cmd_memory(repl, "")
    assert "empty" in out.getvalue().lower() or "no memory" in out.getvalue().lower()


def test_memory_clear_wipes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    mem_path = tmp_path / ".my-agent" / "memory" / "MEMORY.md"
    mem_path.parent.mkdir(parents=True)
    mem_path.write_text("old stuff\n", encoding="utf-8")

    out = io.StringIO()
    repl = _make_repl(out=out)
    cmd_memory(repl, "clear")
    assert not mem_path.exists() or mem_path.read_text().strip() == ""


def test_memory_unknown_subcommand(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    err = io.StringIO()
    repl = _make_repl(err=err)
    cmd_memory(repl, "frobnicate")
    assert "usage" in err.getvalue().lower() or "unknown" in err.getvalue().lower()


def test_commands_table_has_memory():
    assert "memory" in COMMANDS
    assert COMMANDS["memory"] is cmd_memory
