import pytest

from my_agent.tools.files import read_file_tool


def test_read_file_returns_text_content(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello\nworld\n")
    out = read_file_tool.fn({"path": str(p)})
    assert out == "hello\nworld\n"


def test_read_file_unicode(tmp_path):
    p = tmp_path / "u.txt"
    p.write_text("你好,世界 🌏", encoding="utf-8")
    assert read_file_tool.fn({"path": str(p)}) == "你好,世界 🌏"


def test_read_file_missing_raises():
    with pytest.raises(FileNotFoundError):
        read_file_tool.fn({"path": "/nonexistent/xyz_does_not_exist"})


def test_read_file_schema_shape():
    s = read_file_tool.parameters
    assert s["type"] == "object"
    assert "path" in s["properties"]
    assert s["properties"]["path"]["type"] == "string"
    assert s["required"] == ["path"]


def test_read_file_metadata():
    assert read_file_tool.name == "read_file"
    assert read_file_tool.description  # non-empty
    assert callable(read_file_tool.fn)


def test_read_file_via_registry_dispatch(tmp_path):
    """End-to-end through ToolRegistry: invalid path → safe ToolResult."""
    from my_agent.tools.base import ToolRegistry

    reg = ToolRegistry()
    reg.register(read_file_tool)

    p = tmp_path / "x.txt"
    p.write_text("ok")
    res = reg.dispatch("read_file", f'{{"path": "{p}"}}')
    assert res.is_error is False
    assert res.content == "ok"

    res2 = reg.dispatch("read_file", '{"path": "/nope/missing"}')
    assert res2.is_error is True
    assert "FileNotFoundError" in res2.content
