from unittest.mock import MagicMock

from my_agent.cli.main import build_registry, run_once
from my_agent.llm.types import Response, ToolCall


def test_build_registry_includes_read_file():
    reg = build_registry()
    schemas = reg.get_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "read_file" in names


def test_run_once_no_tool_call_returns_text(mocker):
    """Single send when model decides not to call tools."""
    fake_client = MagicMock()
    fake_client.send.return_value = Response(
        content="hello", tool_calls=[], finish_reason="stop"
    )

    out = run_once(fake_client, prompt="hi")
    assert out == "hello"
    assert fake_client.send.call_count == 1


def test_run_once_one_tool_round(mocker, tmp_path):
    """Model asks to read file → harness dispatches → second send returns final text."""
    p = tmp_path / "r.md"
    p.write_text("# my-agent\n")

    fake_client = MagicMock()
    fake_client.send.side_effect = [
        Response(
            content=None,
            tool_calls=[ToolCall(id="c1", name="read_file", arguments=f'{{"path":"{p}"}}')],
            finish_reason="tool_calls",
        ),
        Response(content="项目叫 my-agent", tool_calls=[], finish_reason="stop"),
    ]

    out = run_once(fake_client, prompt="读 README")
    assert "my-agent" in out
    assert fake_client.send.call_count == 2

    # Verify the second send included system + user + assistant(tool_calls) + tool(result).
    second_call_msgs = fake_client.send.call_args_list[1].args[0]
    roles = [m.role for m in second_call_msgs]
    assert roles == ["system", "user", "assistant", "tool"]


def test_run_once_tool_error_still_completes(mocker):
    """If the tool fails, harness must still send the error back so model can recover."""
    fake_client = MagicMock()
    fake_client.send.side_effect = [
        Response(
            content=None,
            tool_calls=[
                ToolCall(id="c1", name="read_file", arguments='{"path":"/nope/missing"}')
            ],
            finish_reason="tool_calls",
        ),
        Response(content="抱歉,文件不存在", tool_calls=[], finish_reason="stop"),
    ]

    out = run_once(fake_client, prompt="读 /nope/missing")
    assert "不存在" in out

    # Tool message should contain the error text.
    second_msgs = fake_client.send.call_args_list[1].args[0]
    tool_msg = next(m for m in second_msgs if m.role == "tool")
    assert "FileNotFoundError" in tool_msg.content


def test_run_once_parallel_tool_calls(mocker, tmp_path):
    """Model requests multiple tools in one turn → all dispatched in order."""
    a = tmp_path / "a.txt"
    a.write_text("AAA")
    b = tmp_path / "b.txt"
    b.write_text("BBB")

    fake_client = MagicMock()
    fake_client.send.side_effect = [
        Response(
            content=None,
            tool_calls=[
                ToolCall(id="c1", name="read_file", arguments=f'{{"path":"{a}"}}'),
                ToolCall(id="c2", name="read_file", arguments=f'{{"path":"{b}"}}'),
            ],
            finish_reason="tool_calls",
        ),
        Response(content="done", tool_calls=[], finish_reason="stop"),
    ]

    out = run_once(fake_client, prompt="读两个文件")
    assert out == "done"

    second_msgs = fake_client.send.call_args_list[1].args[0]
    tool_msgs = [m for m in second_msgs if m.role == "tool"]
    assert len(tool_msgs) == 2
    assert tool_msgs[0].tool_call_id == "c1"
    assert tool_msgs[1].tool_call_id == "c2"
    assert tool_msgs[0].content == "AAA"
    assert tool_msgs[1].content == "BBB"
