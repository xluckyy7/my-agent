"""Tests for hook framework — config loader + HookManager dispatch."""

import json
import sys
from unittest.mock import MagicMock

import pytest

from my_agent.agent.hooks import (
    HOOK_EVENTS,
    HookConfigError,
    HookEvent,
    HookManager,
    HookSpec,
    load_hooks,
)


# ---------------- config loader ----------------


def _write(home, payload):
    p = home / ".my-agent" / "hooks.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_load_hooks_returns_empty_when_missing(tmp_path):
    assert load_hooks(tmp_path) == {}


def test_load_hooks_parses_command_hook(tmp_path):
    _write(tmp_path, {
        "hooks": {
            "PreToolUse": [
                {"type": "command", "command": "echo hi", "matcher": "run_bash", "timeout": 10}
            ]
        }
    })
    out = load_hooks(tmp_path)
    assert "PreToolUse" in out
    [spec] = out["PreToolUse"]
    assert spec.type == "command"
    assert spec.command == "echo hi"
    assert spec.matcher == "run_bash"
    assert spec.timeout == 10


def test_load_hooks_parses_python_hook(tmp_path):
    _write(tmp_path, {
        "hooks": {
            "Stop": [
                {"type": "python", "module": "my_agent.plugins.foo", "function": "on_stop"}
            ]
        }
    })
    [spec] = load_hooks(tmp_path)["Stop"]
    assert spec.type == "python"
    assert spec.module == "my_agent.plugins.foo"
    assert spec.function == "on_stop"


def test_load_hooks_multiple_events_and_hooks(tmp_path):
    _write(tmp_path, {
        "hooks": {
            "PreToolUse": [
                {"type": "command", "command": "a"},
                {"type": "command", "command": "b"},
            ],
            "Stop": [
                {"type": "python", "module": "m", "function": "f"},
            ],
        }
    })
    out = load_hooks(tmp_path)
    assert len(out["PreToolUse"]) == 2
    assert len(out["Stop"]) == 1


def test_load_hooks_rejects_unknown_event(tmp_path):
    _write(tmp_path, {"hooks": {"Bogus": [{"type": "command", "command": "x"}]}})
    with pytest.raises(HookConfigError, match="Bogus"):
        load_hooks(tmp_path)


def test_load_hooks_rejects_unknown_type(tmp_path):
    _write(tmp_path, {"hooks": {"Stop": [{"type": "wasm", "command": "x"}]}})
    with pytest.raises(HookConfigError, match="type"):
        load_hooks(tmp_path)


def test_load_hooks_rejects_command_missing_command(tmp_path):
    _write(tmp_path, {"hooks": {"Stop": [{"type": "command"}]}})
    with pytest.raises(HookConfigError, match="command"):
        load_hooks(tmp_path)


def test_load_hooks_rejects_python_missing_module(tmp_path):
    _write(tmp_path, {"hooks": {"Stop": [{"type": "python", "function": "f"}]}})
    with pytest.raises(HookConfigError, match="module"):
        load_hooks(tmp_path)


# ---------------- HookManager ----------------


def test_fire_calls_python_hook_with_event(mocker):
    """Python hook should be called with the HookEvent."""
    fake_fn = MagicMock()
    fake_mod = MagicMock()
    fake_mod.on_event = fake_fn
    mocker.patch("my_agent.agent.hooks.importlib.import_module", return_value=fake_mod)

    spec = HookSpec(type="python", module="x", function="on_event")
    mgr = HookManager({"PreToolUse": [spec]})

    mgr.fire("PreToolUse", data={"tool_name": "echo"}, subject="echo")

    fake_fn.assert_called_once()
    ev = fake_fn.call_args.args[0]
    assert isinstance(ev, HookEvent)
    assert ev.event == "PreToolUse"
    assert ev.data["tool_name"] == "echo"
    assert ev.timestamp > 0


def test_fire_runs_shell_command_with_payload_on_stdin(mocker):
    fake_run = mocker.patch("my_agent.agent.hooks.subprocess.run")
    spec = HookSpec(type="command", command="cat", timeout=5)
    mgr = HookManager({"Stop": [spec]})

    mgr.fire("Stop", data={"session_id": "abc"})

    fake_run.assert_called_once()
    kwargs = fake_run.call_args.kwargs
    assert kwargs["timeout"] == 5
    payload = json.loads(kwargs["input"])
    assert payload["event"] == "Stop"
    assert payload["data"]["session_id"] == "abc"


def test_fire_matcher_filters_hooks(mocker):
    """matcher is a regex on the `subject` arg; non-match = skip."""
    fake_fn = MagicMock()
    fake_mod = MagicMock()
    fake_mod.on_event = fake_fn
    mocker.patch("my_agent.agent.hooks.importlib.import_module", return_value=fake_mod)

    # Only match tool_name starting with "web_"
    spec = HookSpec(type="python", module="m", function="on_event", matcher=r"^web_")
    mgr = HookManager({"PreToolUse": [spec]})

    mgr.fire("PreToolUse", data={}, subject="read_file")  # no match
    mgr.fire("PreToolUse", data={}, subject="web_fetch")  # match

    assert fake_fn.call_count == 1


def test_fire_empty_matcher_matches_all(mocker):
    fake_fn = MagicMock()
    fake_mod = MagicMock()
    fake_mod.on_event = fake_fn
    mocker.patch("my_agent.agent.hooks.importlib.import_module", return_value=fake_mod)

    spec = HookSpec(type="python", module="m", function="on_event", matcher="")
    mgr = HookManager({"PreToolUse": [spec]})

    mgr.fire("PreToolUse", data={}, subject="anything")
    mgr.fire("PreToolUse", data={}, subject="")

    assert fake_fn.call_count == 2


def test_fire_hook_failure_does_not_crash_agent(mocker, capsys):
    """A buggy hook should log to stderr and let the agent continue."""
    bad_fn = MagicMock(side_effect=RuntimeError("plugin broken"))
    fake_mod = MagicMock()
    fake_mod.on_event = bad_fn
    mocker.patch("my_agent.agent.hooks.importlib.import_module", return_value=fake_mod)

    spec = HookSpec(type="python", module="m", function="on_event")
    mgr = HookManager({"PreToolUse": [spec]})

    # Must not raise
    mgr.fire("PreToolUse", data={})
    err = capsys.readouterr().err
    assert "hook" in err.lower()
    assert "plugin broken" in err


def test_fire_no_hooks_for_event_is_noop():
    mgr = HookManager({})
    mgr.fire("PreToolUse", data={})  # no error


def test_fire_python_module_cached(mocker):
    """importlib.import_module should be called once per module, not per fire."""
    fake_mod = MagicMock()
    fake_mod.fn = MagicMock()
    import_mock = mocker.patch(
        "my_agent.agent.hooks.importlib.import_module", return_value=fake_mod
    )

    spec = HookSpec(type="python", module="my_module", function="fn")
    mgr = HookManager({"Stop": [spec]})

    for _ in range(5):
        mgr.fire("Stop", data={})

    assert import_mock.call_count == 1
    assert fake_mod.fn.call_count == 5


def test_HOOK_EVENTS_lists_supported():
    """Public catalog of event names — pin this to catch accidental rename."""
    expected = {
        "SessionStart", "UserPromptSubmit",
        "PreModelCall", "PostModelCall",
        "PreToolUse", "PostToolUse",
        "Stop",
    }
    assert set(HOOK_EVENTS) == expected
