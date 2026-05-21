from my_agent.cli.main import build_registry


def test_build_registry_includes_all_v07_tools(tmp_path):
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
