from my_agent.cli.main import build_registry


def test_build_registry_includes_all_v03_tools():
    reg = build_registry()
    names = [s["function"]["name"] for s in reg.get_schemas()]
    assert "read_file" in names
    assert "write_file" in names
    assert "run_bash" in names
