# MCP Demo Server Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 `examples/mcp_demo_server/` 下用 FastMCP 实现一个三件套(tools / resources / prompts)俱全的玩具 MCP server,完成与 v0.8 client 的协议两端闭环。

**Architecture:** 单文件 `server.py` 承载 6 个原语函数(2 tools + 2 resources + 2 prompts),用 stdio 传输。独立 `pyproject.toml` 隔离依赖,独立 `tests/` 目录覆盖单测 + 子进程 e2e。最终通过编辑 `~/.my-agent/mcp.json` 让 v0.8 my-agent CLI 调到。

**Tech Stack:** Python 3.10+, `mcp>=1.12`(官方 SDK 中的 FastMCP),pytest,asyncio + AsyncExitStack(e2e 测试)。

**Reference:** [设计文档](./2026-05-21-mcp-demo-server-design.md) / [SDK README](https://github.com/modelcontextprotocol/python-sdk)

---

## 总览

9 个任务,每个 2-10 分钟,TDD 驱动,每任务一次 commit。

| # | 任务 | 产物 |
|---|---|---|
| 1 | Scaffold 目录 + pyproject + 装依赖 | 可空跑 `python server.py` |
| 2 | Tool `add` (TDD) | 第一个原语跑通 |
| 3 | Tool `get_server_time` (TDD) | 无参 tool 对照 |
| 4 | Resource 静态 `demo://docs/welcome` (TDD) | resource 跑通 |
| 5 | Resource URI 模板 `demo://greeting/{name}` (TDD) | URI template 形态 |
| 6 | Prompt `summarize_paragraph` (TDD) | string-return prompt |
| 7 | Prompt `code_review` (TDD) | list[Message]-return prompt |
| 8 | E2E 协议测试(子进程 + ClientSession) | 三原语都能远程调到 |
| 9 | README + 挂到 v0.8 client 实跑 | 真正闭环 |

---

## Task 1: Scaffold + 依赖

**Files:**
- Create: `examples/mcp_demo_server/pyproject.toml`
- Create: `examples/mcp_demo_server/README.md` (占位,Task 9 补完)
- Create: `examples/mcp_demo_server/server.py`(最小空 server)
- Create: `examples/mcp_demo_server/tests/__init__.py`(空文件)

**Step 1: 建目录结构**

```bash
mkdir -p examples/mcp_demo_server/tests
touch examples/mcp_demo_server/tests/__init__.py
touch examples/mcp_demo_server/README.md
```

**Step 2: 写 `pyproject.toml`**

完整内容写入 `examples/mcp_demo_server/pyproject.toml`:

```toml
[project]
name = "mcp-demo-server"
version = "0.1.0"
description = "Toy MCP server for learning the protocol from the producer side"
requires-python = ">=3.10"
dependencies = [
    "mcp>=1.12",
]

[project.optional-dependencies]
dev = [
    "pytest>=7",
    "pytest-asyncio>=0.23",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["."]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]
```

要点:
- `pythonpath = ["."]` 让 `tests/` 里能 `from server import ...`
- `asyncio_mode = "auto"` — pytest-asyncio 不需要手写 `@pytest.mark.asyncio`

**Step 3: 写最小 `server.py`(空骨架)**

```python
"""
Toy MCP server — three-primitive learning demo.

Run with: python server.py  (stdio transport, blocks waiting on stdin)

This module wires up the FastMCP server. Each primitive is added in its
own Task with a paired test. See ../README.md for the protocol walk-through.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo")


if __name__ == "__main__":
    mcp.run()  # stdio is the default transport
```

**Step 4: 装依赖 + 跑空 server 验证**

```bash
cd examples/mcp_demo_server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

预期最后一行类似 `Successfully installed mcp-demo-server-0.1.0 mcp-1.12.x ...`

```bash
timeout 2s python server.py
echo "exit=$?"
```

预期:`exit=124`(timeout 杀掉,因为 server 在阻塞等 stdin,这正确)。**任何非 124 / 137 的退出码都说明 server 启动报错,先看 stderr。**

**Step 5: Commit**

```bash
git add examples/mcp_demo_server/
git commit -m "feat(mcp-demo): scaffold demo server skeleton"
```

---

## Task 2: Tool `add` (TDD)

**Files:**
- Create: `examples/mcp_demo_server/tests/test_tools.py`
- Modify: `examples/mcp_demo_server/server.py`(在 `mcp = FastMCP(...)` 之后、`if __name__` 之前加)

**Step 1: 写失败测试**

`examples/mcp_demo_server/tests/test_tools.py`:

```python
"""Unit tests for tool functions exposed via @mcp.tool()."""

from server import add


def test_add_returns_sum():
    assert add(2, 3) == 5


def test_add_negative_numbers():
    assert add(-4, 1) == -3
```

**Step 2: 跑测试,确认失败**

```bash
cd examples/mcp_demo_server && pytest tests/test_tools.py -v
```

预期:`ImportError: cannot import name 'add'`

**Step 3: 加最小实现**

在 `server.py` 中 `mcp = FastMCP("demo")` 之后插入:

```python
@mcp.tool()
def add(a: int, b: int) -> int:
    """Return a + b.

    LEARN: type hints are not decoration — FastMCP reflects them to JSON Schema
    that the client lists via tools/list. The docstring becomes tool.description.
    """
    return a + b
```

**Step 4: 跑测试,确认通过**

```bash
pytest tests/test_tools.py -v
```

预期:`2 passed`

**Step 5: Commit**

```bash
git add examples/mcp_demo_server/server.py examples/mcp_demo_server/tests/test_tools.py
git commit -m "feat(mcp-demo): tool add — first MCP primitive (TDD)"
```

---

## Task 3: Tool `get_server_time` (TDD)

**Files:**
- Modify: `examples/mcp_demo_server/tests/test_tools.py`
- Modify: `examples/mcp_demo_server/server.py`

**Step 1: 添加失败测试**

在 `test_tools.py` 末尾追加:

```python
import re

from server import get_server_time


def test_get_server_time_iso8601():
    result = get_server_time()
    # ISO 8601 in UTC, e.g. "2026-05-21T08:23:14.123456+00:00"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", result)
    assert result.endswith("+00:00") or result.endswith("Z")
```

**Step 2: 跑测试,确认失败**

```bash
pytest tests/test_tools.py::test_get_server_time_iso8601 -v
```

预期:`ImportError: cannot import name 'get_server_time'`

**Step 3: 加最小实现**

在 `server.py` 中 `add` 之后追加:

```python
from datetime import datetime, timezone


@mcp.tool()
def get_server_time() -> str:
    """Return current server-side ISO 8601 timestamp (UTC).

    LEARN: contrast with `add` — no parameters. FastMCP still produces a
    valid (empty-properties) JSON Schema for tools/list. Useful baseline.
    """
    return datetime.now(timezone.utc).isoformat()
```

**Step 4: 跑测试,确认通过**

```bash
pytest tests/test_tools.py -v
```

预期:`3 passed`

**Step 5: Commit**

```bash
git add examples/mcp_demo_server/
git commit -m "feat(mcp-demo): tool get_server_time — no-arg variant"
```

---

## Task 4: Resource 静态 URI `demo://docs/welcome` (TDD)

**Files:**
- Create: `examples/mcp_demo_server/tests/test_resources.py`
- Modify: `examples/mcp_demo_server/server.py`

**Step 1: 写失败测试**

`tests/test_resources.py`:

```python
"""Unit tests for @mcp.resource handlers."""

from server import welcome_doc


def test_welcome_doc_returns_markdown():
    content = welcome_doc()
    assert content.startswith("# ")
    assert "MCP" in content
```

**Step 2: 跑测试,确认失败**

```bash
pytest tests/test_resources.py -v
```

预期:`ImportError: cannot import name 'welcome_doc'`

**Step 3: 加最小实现**

`server.py` 末尾(`if __name__` 之前)追加:

```python
@mcp.resource("demo://docs/welcome")
def welcome_doc() -> str:
    """Static markdown welcoming the agent.

    LEARN: resources expose READ-ONLY data, addressable by URI. Compare to
    REST GET. The URI scheme `demo://` is arbitrary — clients ask via
    resources/list and read via resources/read.
    """
    return (
        "# Welcome to the MCP Demo Server\n\n"
        "This is a learning MCP server. It exposes three primitives:\n"
        "- 2 tools (function-call style)\n"
        "- 2 resources (URI-addressable data)\n"
        "- 2 prompts (server-supplied templates)\n"
    )
```

**Step 4: 跑测试,确认通过**

```bash
pytest tests/test_resources.py -v
```

预期:`1 passed`

**Step 5: Commit**

```bash
git add examples/mcp_demo_server/
git commit -m "feat(mcp-demo): resource welcome_doc — static URI"
```

---

## Task 5: Resource URI 模板 `demo://greeting/{name}` (TDD)

**Files:**
- Modify: `examples/mcp_demo_server/tests/test_resources.py`
- Modify: `examples/mcp_demo_server/server.py`

**Step 1: 添加失败测试**

`test_resources.py` 末尾追加:

```python
from server import greeting


def test_greeting_renders_name():
    assert greeting("World") == "Hello, World!"


def test_greeting_handles_unicode():
    assert greeting("世界") == "Hello, 世界!"
```

**Step 2: 跑测试,确认失败**

```bash
pytest tests/test_resources.py -v
```

预期:`ImportError: cannot import name 'greeting'`

**Step 3: 加最小实现**

`server.py` 中,在 `welcome_doc` 之后追加:

```python
@mcp.resource("demo://greeting/{name}")
def greeting(name: str) -> str:
    """Parameterized greeting; {name} is RFC 6570 URI Template.

    LEARN: when client requests `demo://greeting/Alice`, FastMCP matches
    against the URI template and binds `name="Alice"`. This is the
    resource-side analog of REST `/users/{id}`.
    """
    return f"Hello, {name}!"
```

**Step 4: 跑测试,确认通过**

```bash
pytest tests/test_resources.py -v
```

预期:`3 passed`

**Step 5: Commit**

```bash
git add examples/mcp_demo_server/
git commit -m "feat(mcp-demo): resource greeting — URI template variant"
```

---

## Task 6: Prompt `summarize_paragraph` (TDD)

**Files:**
- Create: `examples/mcp_demo_server/tests/test_prompts.py`
- Modify: `examples/mcp_demo_server/server.py`

**Step 1: 写失败测试**

`tests/test_prompts.py`:

```python
"""Unit tests for @mcp.prompt handlers."""

from server import summarize_paragraph


def test_summarize_paragraph_returns_string():
    result = summarize_paragraph()
    assert isinstance(result, str)
    assert "summar" in result.lower()
```

**Step 2: 跑测试,确认失败**

```bash
pytest tests/test_prompts.py -v
```

预期:`ImportError: cannot import name 'summarize_paragraph'`

**Step 3: 加最小实现**

`server.py` 末尾追加:

```python
@mcp.prompt()
def summarize_paragraph() -> str:
    """No-arg prompt asking to summarize the most recent message.

    LEARN: prompts are SERVER-SUPPLIED templates. Client UIs (e.g. Claude
    Desktop's slash-command list) surface them so users can invoke
    "the right way to ask this server" without composing themselves.
    Returning a plain string is the simplest form.
    """
    return "Please summarize the previous message in one concise sentence."
```

**Step 4: 跑测试,确认通过**

```bash
pytest tests/test_prompts.py -v
```

预期:`1 passed`

**Step 5: Commit**

```bash
git add examples/mcp_demo_server/
git commit -m "feat(mcp-demo): prompt summarize_paragraph — string return"
```

---

## Task 7: Prompt `code_review` (TDD)

**Files:**
- Modify: `examples/mcp_demo_server/tests/test_prompts.py`
- Modify: `examples/mcp_demo_server/server.py`

**Step 1: 添加失败测试**

`test_prompts.py` 末尾追加:

```python
from server import code_review


def test_code_review_returns_message_list():
    msgs = code_review(language="python", code="print('hi')")
    assert isinstance(msgs, list)
    assert len(msgs) >= 2
    # Each message should have role="user"
    assert all(m.role == "user" for m in msgs)


def test_code_review_injects_code_and_language():
    msgs = code_review(language="rust", code="fn main() {}")
    flat = " ".join(getattr(m.content, "text", "") for m in msgs)
    assert "rust" in flat
    assert "fn main()" in flat
```

**Step 2: 跑测试,确认失败**

```bash
pytest tests/test_prompts.py -v
```

预期:`ImportError: cannot import name 'code_review'`

**Step 3: 加最小实现**

`server.py` 末尾追加:

```python
from mcp.server.fastmcp.prompts import base


@mcp.prompt()
def code_review(language: str, code: str) -> list[base.Message]:
    """Multi-message review prompt; arguments injected into the conversation.

    LEARN: prompts can return list[Message] when you want a multi-turn
    primer. Compare to summarize_paragraph (single string). The client
    reads `prompts/get` response as `messages: [...]` regardless.
    """
    return [
        base.UserMessage(f"Please review the following {language} code:"),
        base.UserMessage(f"```{language}\n{code}\n```"),
    ]
```

**Step 4: 跑测试,确认通过**

```bash
pytest tests/test_prompts.py -v
```

预期:`3 passed`

**Step 5: 整体回归**

```bash
pytest tests/ -v
```

预期:`9 passed`

**Step 6: Commit**

```bash
git add examples/mcp_demo_server/
git commit -m "feat(mcp-demo): prompt code_review — multi-message return"
```

---

## Task 8: E2E 协议测试(子进程 + ClientSession)

**Files:**
- Create: `examples/mcp_demo_server/tests/test_e2e.py`

**Step 1: 写 e2e 测试**

`tests/test_e2e.py`:

```python
"""
End-to-end protocol test — spawns server.py as a subprocess and drives it
with the official mcp ClientSession over stdio. Validates that all three
primitives are reachable through the actual protocol, not just as Python
function calls.

LEARN: this is the same shape v0.8 client uses internally. Re-doing the
async dance from the test side mirrors src/my_agent/mcp_layer/client.py.
"""

import sys
from pathlib import Path

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER = str(Path(__file__).parent.parent / "server.py")


@pytest.fixture
def server_params():
    # Use the SAME python that's running the test — guarantees the venv where
    # `mcp` is installed is in scope.
    return StdioServerParameters(command=sys.executable, args=[SERVER])


async def test_initialize_and_list_tools(server_params):
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {"add", "get_server_time"} <= names


async def test_call_tool_add(server_params):
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("add", {"a": 7, "b": 8})
            assert result.isError is False
            # Result is a list of content blocks; first one is text "15"
            assert any("15" in getattr(c, "text", "") for c in result.content)


async def test_list_and_read_resources(server_params):
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            resources = await session.list_resources()
            # Static resources show up in list_resources; templated ones may
            # show up in list_resource_templates depending on SDK version.
            uris = {str(r.uri) for r in resources.resources}
            assert "demo://docs/welcome" in uris

            from pydantic import AnyUrl
            content = await session.read_resource(AnyUrl("demo://docs/welcome"))
            text = content.contents[0].text
            assert "Welcome" in text


async def test_read_templated_resource(server_params):
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            from pydantic import AnyUrl
            content = await session.read_resource(AnyUrl("demo://greeting/Alice"))
            text = content.contents[0].text
            assert text == "Hello, Alice!"


async def test_list_and_get_prompts(server_params):
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            prompts = await session.list_prompts()
            names = {p.name for p in prompts.prompts}
            assert {"summarize_paragraph", "code_review"} <= names

            result = await session.get_prompt(
                "code_review",
                arguments={"language": "python", "code": "x = 1"},
            )
            joined = " ".join(
                getattr(m.content, "text", "") for m in result.messages
            )
            assert "python" in joined
            assert "x = 1" in joined
```

**Step 2: 跑 e2e**

```bash
pytest tests/test_e2e.py -v
```

预期:`5 passed`(可能慢 3-10s,因为要起子进程)

**踩坑可能性提醒(执行时若遇到):**
- `event loop closed` → 检查 async with 嵌套顺序,`stdio_client` 必须包在 `ClientSession` 外面
- `read_resource` 找不到 templated URI → 不同 SDK 版本可能走 `list_resource_templates` 路径,失败时跑 `pytest tests/test_e2e.py::test_read_templated_resource -v -s` 看真实错误,可能需要把 templated 资源测试拆出来或调整
- `Tool result.isError is None` → SDK 类型迁移,改成 `assert not result.isError`(支持 None / False 都过)

**Step 3: Commit**

```bash
git add examples/mcp_demo_server/tests/test_e2e.py
git commit -m "test(mcp-demo): e2e protocol roundtrip via stdio_client"
```

---

## Task 9: README + 挂到 v0.8 client 实跑

**Files:**
- Modify: `examples/mcp_demo_server/README.md`
- Modify(本机): `~/.my-agent/mcp.json`

**Step 1: 写 README**

`examples/mcp_demo_server/README.md`:

````markdown
# MCP Demo Server

玩具 MCP server,覆盖三个原语(tools / resources / prompts)各 2 个,
用 FastMCP 实现。配套 [设计文档](../../docs/plans/2026-05-21-mcp-demo-server-design.md)。

## 快速跑

```bash
cd examples/mcp_demo_server
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -v          # 9 unit + 5 e2e 测试
python server.py   # 启动 stdio server,等待 client 连接(Ctrl-C 退出)
```

## 暴露的原语

| 类型 | 名字 | 形态 |
|---|---|---|
| tool | `add(a, b)` | 有参,纯函数 |
| tool | `get_server_time()` | 无参,带"副作用"(读时钟) |
| resource | `demo://docs/welcome` | 静态 URI |
| resource | `demo://greeting/{name}` | URI template |
| prompt | `summarize_paragraph` | 返回 string |
| prompt | `code_review(language, code)` | 返回 list[Message] |

## 协议关键时刻(手画)

```
client                                server
  │                                      │
  ├─ initialize ────────────────────────▶│  能力协商
  │◀───────────────── initialize result ─┤  (tools ✓ resources ✓ prompts ✓)
  │                                      │
  ├─ tools/list ────────────────────────▶│
  │◀──── [{name:"add", inputSchema:...}, ┤
  │                                      │
  ├─ tools/call {name:"add",a:3,b:5} ───▶│
  │◀────────── [{type:"text", text:"8"}] ┤
```

要点:`initialize` 不只是"连上",而是双方协商**有哪些能力**。
如果 server.py 一行 `@mcp.resource` 都不写,client 拿不到 resources/* 能力。

## 挂到 my-agent v0.8 client

编辑 `~/.my-agent/mcp.json`,加 `demo` server:

```json
{
  "servers": {
    "demo": {
      "command": "/abs/path/to/examples/mcp_demo_server/.venv/bin/python",
      "args": ["/abs/path/to/examples/mcp_demo_server/server.py"]
    }
  }
}
```

注意:`command` 必须用 demo server venv 里的 python(否则找不到 `mcp` 包)。

启动 my-agent:

```bash
cd /path/to/my-agent
source .venv/bin/activate
python -m my_agent
```

进入 REPL 后试:

```
>>> /mcp
demo:
  demo__add — Return a + b.
  demo__get_server_time — Return current server-side ISO 8601 ...

>>> 用 demo 的 add 工具算 3 + 5
▸ demo__add {"a": 3, "b": 5}
✓ 0.45s 8
3 + 5 = 8
```

## 学到了什么(给未来的我)

- FastMCP 把 type hints 自动反射到 JSON Schema,所以 hints 不可省。
- Resource URI template `{name}` = RFC 6570,resources/read 时绑定。
- Prompt 返 list[Message] 比 string 更灵活,但 string 形态对应"快捷指令式"用法。
- `initialize` 的 capabilities 由 server 实际注册的装饰器决定 — 不写就没有。
- 与 v0.8 client 对照:client 端踩的 AsyncExitStack / event loop 问题,server 端测试同样会撞到。
````

**Step 2: 配置 `~/.my-agent/mcp.json`**

```bash
ABS=$(cd examples/mcp_demo_server && pwd)
mkdir -p ~/.my-agent
# 备份现有 mcp.json(如果有)
[ -f ~/.my-agent/mcp.json ] && cp ~/.my-agent/mcp.json ~/.my-agent/mcp.json.bak.$(date +%s)
cat > ~/.my-agent/mcp.json <<EOF
{
  "servers": {
    "demo": {
      "command": "$ABS/.venv/bin/python",
      "args": ["$ABS/server.py"]
    }
  }
}
EOF
cat ~/.my-agent/mcp.json
```

注:如果原文件已有其他 servers,**手动合并**而非覆盖,上面命令会备份旧版到 `.bak.<timestamp>`。

**Step 3: 真实跑 my-agent 验收**

```bash
cd /Users/xinqi/Projects/study/my-agent
source .venv/bin/activate
python -m my_agent <<EOF
/mcp
EOF
```

预期 `/mcp` 输出包含 `demo:` 段落,列出 `demo__add` 和 `demo__get_server_time`。

接着真互动一次:

```bash
python -m my_agent "调 demo 的 add 工具算 3+5,只回答数字"
```

预期:模型主动调 `demo__add({"a":3,"b":5})`,工具指示器显示成功,最终回答含 `8`。

**Step 4: Commit**

```bash
git add examples/mcp_demo_server/README.md
git commit -m "docs(mcp-demo): README + v0.8 client 实跑闭环"
```

`~/.my-agent/mcp.json` 是本机配置,**不要 commit 进 repo**。

**Step 5: 写 retro(可选,推荐)**

```bash
touch docs/notes/iter-mcp-demo-retro.md
```

模板按现有 retro 的结构(做了什么 / 关键决策 / 学到的概念 / 踩的坑 / 已知限制 / 我的补充)。这一步不强制,但与项目惯例一致。

---

## 完成验收清单

- [ ] `pytest examples/mcp_demo_server/tests/ -v` 全过(14 tests)
- [ ] `python examples/mcp_demo_server/server.py` 能起服务(timeout 测试通过)
- [ ] my-agent CLI 中 `/mcp` 看得到 `demo:` server
- [ ] my-agent 能成功调 `demo__add` 并拿到正确结果
- [ ] 9 个 commit,每个 commit 单独可读
- [ ] README 给出可复制的 mcp.json 样板

---

## 已知风险与备案

| 风险 | 备案 |
|---|---|
| FastMCP 装饰器 API 在 1.12.x 后再次微调 | 测试失败时,先 `pip show mcp` 确认版本,再到 SDK README 验对应小节代码 |
| `read_resource` 对 templated URI 在某些版本走不同代码路径 | Task 8 已提示;失败时把该测试单独拆,改用 `list_resource_templates` |
| my-agent v0.8 client 端 namespacing(`demo__add`)与 server 注册名不符 | 检查 `src/my_agent/mcp_layer/adapter.py`mcp_tool_to_internal 的命名规则,与本 demo 一致 |
| Prompt 测试中 `m.content` 结构假设 | 若 `getattr(m.content, "text", "")` 总返空,改为 `m.content.text`(直接属性);失败说明 SDK 改了 content block 结构 |
