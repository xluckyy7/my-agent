import io
from unittest.mock import MagicMock

import pytest

from my_agent.agent.conversation import Conversation
from my_agent.cli.repl import COMMANDS, Repl, cmd_help, cmd_load, cmd_quit, cmd_reset, cmd_save


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
