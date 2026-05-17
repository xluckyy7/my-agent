from my_agent.tools.base import Tool, ToolRegistry, ToolResult


def _echo(args: dict) -> str:
    return args["x"]


def _make_echo_tool() -> Tool:
    return Tool(
        name="echo",
        description="echo input",
        parameters={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
        fn=_echo,
    )


def test_registry_register_and_dispatch_ok():
    reg = ToolRegistry()
    reg.register(_make_echo_tool())
    res = reg.dispatch("echo", '{"x":"hello"}')
    assert isinstance(res, ToolResult)
    assert res.content == "hello"
    assert res.is_error is False


def test_registry_dispatch_unknown_tool():
    reg = ToolRegistry()
    res = reg.dispatch("nope", "{}")
    assert res.is_error is True
    assert "unknown" in res.content.lower()


def test_registry_dispatch_invalid_json():
    reg = ToolRegistry()
    reg.register(_make_echo_tool())
    res = reg.dispatch("echo", "{not json")
    assert res.is_error is True
    assert "json" in res.content.lower()


def test_registry_dispatch_fn_raises():
    def boom(args):
        raise ValueError("kaboom")

    reg = ToolRegistry()
    reg.register(Tool(name="boom", description="x", parameters={}, fn=boom))
    res = reg.dispatch("boom", "{}")
    assert res.is_error is True
    assert "kaboom" in res.content
    assert "ValueError" in res.content


def test_registry_dispatch_returns_string_for_non_string_output():
    reg = ToolRegistry()
    reg.register(Tool(name="num", description="", parameters={}, fn=lambda a: 42))
    res = reg.dispatch("num", "{}")
    assert res.content == "42"
    assert res.is_error is False


def test_registry_get_schemas_openai_format():
    reg = ToolRegistry()
    reg.register(_make_echo_tool())
    schemas = reg.get_schemas()
    assert schemas == [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "echo input",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                    "required": ["x"],
                },
            },
        }
    ]


def test_registry_get_schemas_empty():
    reg = ToolRegistry()
    assert reg.get_schemas() == []


def test_registry_register_overwrites_same_name():
    reg = ToolRegistry()
    reg.register(Tool(name="t", description="v1", parameters={}, fn=lambda a: "v1"))
    reg.register(Tool(name="t", description="v2", parameters={}, fn=lambda a: "v2"))
    assert reg.dispatch("t", "{}").content == "v2"
    assert reg.get_schemas()[0]["function"]["description"] == "v2"
