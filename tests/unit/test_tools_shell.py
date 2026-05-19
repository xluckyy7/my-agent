import pytest

from my_agent.tools.shell import run_bash_tool


def test_run_bash_echo_hello(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = run_bash_tool.fn({"command": "echo hello"})
    assert "hello" in out
    assert "exit code: 0" in out


def test_run_bash_captures_stderr(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = run_bash_tool.fn({"command": "echo to-stderr 1>&2"})
    assert "to-stderr" in out
    assert "stderr" in out.lower()


def test_run_bash_nonzero_exit_code(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = run_bash_tool.fn({"command": "exit 7"})
    assert "exit code: 7" in out


def test_run_bash_runs_in_cwd(tmp_path, monkeypatch):
    """pwd should reflect the process cwd at call time."""
    monkeypatch.chdir(tmp_path)
    out = run_bash_tool.fn({"command": "pwd"})
    # macOS's /tmp is symlinked to /private/tmp; accept both forms
    assert str(tmp_path) in out or str(tmp_path).replace("/private", "") in out


def test_run_bash_timeout_kills(tmp_path, monkeypatch):
    """Sleep longer than timeout → must raise subprocess.TimeoutExpired, which
    ToolRegistry.dispatch will convert to is_error=True."""
    import subprocess

    monkeypatch.chdir(tmp_path)
    with pytest.raises(subprocess.TimeoutExpired):
        run_bash_tool.fn({"command": "sleep 5", "timeout": 1})


def test_run_bash_default_timeout_used(tmp_path, monkeypatch):
    """Default timeout (30s) is plenty for fast commands."""
    monkeypatch.chdir(tmp_path)
    out = run_bash_tool.fn({"command": "true"})  # noop, exit 0
    assert "exit code: 0" in out


def test_run_bash_schema_shape():
    s = run_bash_tool.parameters
    assert s["type"] == "object"
    assert "command" in s["properties"]
    assert s["properties"]["command"]["type"] == "string"
    # timeout is optional
    assert "timeout" in s["properties"]
    assert s["properties"]["timeout"]["type"] == "integer"
    assert s["required"] == ["command"]


def test_run_bash_metadata():
    assert run_bash_tool.name == "run_bash"
    assert run_bash_tool.description
    assert callable(run_bash_tool.fn)


def test_run_bash_output_includes_both_streams(tmp_path, monkeypatch):
    """Command emitting both stdout and stderr — both should appear in output."""
    monkeypatch.chdir(tmp_path)
    out = run_bash_tool.fn({"command": "echo OUT; echo ERR 1>&2"})
    assert "OUT" in out
    assert "ERR" in out


def test_run_bash_via_registry_dispatch_timeout(tmp_path, monkeypatch):
    """End-to-end: timeout raises → Registry catches → is_error=True."""
    from my_agent.tools.base import ToolRegistry

    monkeypatch.chdir(tmp_path)
    reg = ToolRegistry()
    reg.register(run_bash_tool)

    res = reg.dispatch("run_bash", '{"command": "sleep 5", "timeout": 1}')
    assert res.is_error is True
    assert "Timeout" in res.content or "timeout" in res.content.lower()


def test_run_bash_via_registry_dispatch_success(tmp_path, monkeypatch):
    from my_agent.tools.base import ToolRegistry

    monkeypatch.chdir(tmp_path)
    reg = ToolRegistry()
    reg.register(run_bash_tool)

    res = reg.dispatch("run_bash", '{"command": "echo hi"}')
    assert res.is_error is False
    assert "hi" in res.content
