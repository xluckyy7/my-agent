from my_agent.cli.main import build_registry


def test_build_registry_includes_all_v08_builtin_tools(tmp_path):
    reg = build_registry(home=tmp_path)
    names = [s["function"]["name"] for s in reg.get_schemas()]
    assert "read_file" in names
    assert "write_file" in names
    assert "run_bash" in names
    assert "web_fetch" in names
    assert "remember" in names


def test_build_registry_skips_web_search_without_tavily_key(monkeypatch, tmp_path):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    reg = build_registry(home=tmp_path)
    names = [s["function"]["name"] for s in reg.get_schemas()]
    assert "web_search" not in names


def test_build_registry_includes_web_search_when_tavily_key_set(monkeypatch, tmp_path):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-fake")
    reg = build_registry(home=tmp_path)
    names = [s["function"]["name"] for s in reg.get_schemas()]
    assert "web_search" in names


def test_build_registry_loads_mcp_servers_from_config(monkeypatch, tmp_path, mocker):
    """When ~/.my-agent/mcp.json defines a server, its tools get registered
    with namespaced names <server>__<tool>."""
    import json

    cfg_path = tmp_path / ".my-agent" / "mcp.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({
        "servers": {
            "fakeserver": {"command": "true", "args": []}
        }
    }))

    # Avoid actually spawning subprocesses; substitute discovered tools.
    from my_agent.tools.base import Tool
    fake_tool = Tool(
        name="fakeserver__hello",
        description="a fake mcp tool",
        parameters={"type": "object", "properties": {}},
        fn=lambda a: "ok",
    )
    mocker.patch(
        "my_agent.cli.main.build_mcp_tools",
        return_value=[fake_tool],
    )

    reg = build_registry(home=tmp_path)
    names = [s["function"]["name"] for s in reg.get_schemas()]
    assert "fakeserver__hello" in names
