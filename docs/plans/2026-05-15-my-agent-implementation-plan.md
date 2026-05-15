# my-agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 从 0 搭建一个 Python CLI 通用 agent,裸写 OpenAI 兼容协议,自造 harness,边写边学。

**Architecture:** 单进程 Python CLI,`openai` SDK 走 DashScope 兼容端点调 Qwen。内部消息模型用 OpenAI 原生格式(`role/content/tool_calls/tool_call_id`)。AgentLoop 实现 ReAct 式循环:user → assistant → tool → assistant → stop。

**Tech Stack:** Python 3.11+ / openai>=1.40 / python-dotenv / pytest / pytest-mock / typer + rich (Iter 4+) / tiktoken (Iter 5+) / fastapi + uvicorn (Iter 10)

**Reference Design:** `docs/plans/2026-05-15-my-agent-design.md`

---

## 计划组织方式

| 范围 | 详细程度 | 说明 |
|---|---|---|
| Iter 0-3 | bite-sized TDD 步骤 | 基础与学习关键期,逐步逐测试编码 |
| Iter 4-10 | milestone + 关键契约 + 验收标准 | 起步时建议重新 invoke `writing-plans` 把当前 iter 拆成 bite-sized 任务 |

每个 iter 完成后:`git tag v0.X` + 在 `docs/notes/iter-X-retro.md` 写一段 200 字的回顾(踩了什么坑、和论文/文档对照学到什么)。

---

# Phase 0: 项目初始化

## Task 0.1: 创建项目骨架

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/my_agent/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`(空文件)

**Step 1: 写 pyproject.toml**

```toml
[project]
name = "my-agent"
version = "0.0.0"
description = "A from-scratch personal agent built for learning"
requires-python = ">=3.11"
dependencies = [
    "openai>=1.40",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "ruff>=0.5",
]

[project.scripts]
my-agent = "my_agent.cli.main:app"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
markers = ["integration: real-API tests, skipped by default"]
addopts = "-m 'not integration'"
testpaths = ["tests"]
```

**Step 2: 写 .gitignore**

```gitignore
__pycache__/
*.py[cod]
.venv/
venv/
.env
*.egg-info/
dist/
build/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
```

**Step 3: 写 .env.example**

```env
DASHSCOPE_API_KEY=sk-your-key-here
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DEFAULT_MODEL=qwen-plus
# Optional, for later comparison:
# ANTHROPIC_API_KEY=sk-ant-...
```

**Step 4: 创建空 __init__.py 与 conftest.py**

```bash
touch src/my_agent/__init__.py tests/__init__.py tests/conftest.py
```

**Step 5: 安装并验证**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest --version
```

Expected: pytest 版本号正常输出。

**Step 6: 提交**

```bash
git add pyproject.toml .gitignore .env.example src tests
git commit -m "chore: bootstrap project skeleton"
```

---

## Task 0.2: Config 模块 + 测试

**Files:**
- Create: `src/my_agent/config.py`
- Create: `tests/unit/test_config.py`

**Step 1: 写测试(失败)**

`tests/unit/test_config.py`:
```python
import os
import pytest
from my_agent.config import Config, load_config


def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("DEFAULT_MODEL", "qwen-plus")
    cfg = load_config()
    assert cfg.api_key == "test-key"
    assert cfg.base_url == "https://example.com/v1"
    assert cfg.model == "qwen-plus"


def test_load_config_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        load_config()


def test_config_defaults():
    cfg = Config(api_key="k")
    assert cfg.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert cfg.model == "qwen-plus"
    assert cfg.max_tokens == 4096
```

**Step 2: 跑测试确认失败**

```bash
pytest tests/unit/test_config.py -v
```

Expected: ImportError 或 ModuleNotFoundError。

**Step 3: 写最小实现**

`src/my_agent/config.py`:
```python
import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class Config:
    api_key: str
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen-plus"
    max_tokens: int = 4096


def load_config() -> Config:
    load_dotenv()
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY not set in environment or .env")
    return Config(
        api_key=api_key,
        base_url=os.environ.get(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        model=os.environ.get("DEFAULT_MODEL", "qwen-plus"),
    )
```

**Step 4: 跑测试确认通过**

```bash
pytest tests/unit/test_config.py -v
```

Expected: 3 passed.

**Step 5: 提交**

```bash
git add src/my_agent/config.py tests/unit/test_config.py
git commit -m "feat(config): load config from env with defaults"
```

---

# Phase 1: Iter 0 — 最小 chat loop

**目标:** 一次 API 调用,终端打印结果。不带工具、不带历史,纯 hello world。
**验收:** 命令行 `python -m my_agent "你好"` 输出 Qwen 的回复。
**Git tag:** `v0.0`
**配套阅读:**
- OpenAI Chat Completions API 文档(`/v1/chat/completions`)
- DashScope OpenAI 兼容文档:`https://help.aliyun.com/zh/model-studio/developer-reference/compatibility-of-openai-with-dashscope`

---

## Task I0.1: LLM types(空容器)

**Files:**
- Create: `src/my_agent/llm/__init__.py`
- Create: `src/my_agent/llm/types.py`
- Create: `tests/unit/test_llm_types.py`

**Step 1: 写测试**

```python
from my_agent.llm.types import Message, ToolCall, Response


def test_message_simple_text():
    m = Message(role="user", content="hello")
    assert m.to_api_dict() == {"role": "user", "content": "hello"}


def test_message_assistant_with_tool_calls():
    m = Message(
        role="assistant",
        content=None,
        tool_calls=[ToolCall(id="c1", name="read_file", arguments='{"path":"a"}')],
    )
    d = m.to_api_dict()
    assert d["role"] == "assistant"
    assert d["content"] is None
    assert d["tool_calls"] == [{
        "id": "c1",
        "type": "function",
        "function": {"name": "read_file", "arguments": '{"path":"a"}'},
    }]


def test_message_tool_result():
    m = Message(role="tool", tool_call_id="c1", name="read_file", content="ok")
    assert m.to_api_dict() == {
        "role": "tool",
        "tool_call_id": "c1",
        "name": "read_file",
        "content": "ok",
    }
```

**Step 2: 跑测试 → 失败**

```bash
pytest tests/unit/test_llm_types.py -v
```

**Step 3: 实现**

```python
# src/my_agent/llm/types.py
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str          # OpenAI 规定是 JSON 字符串

    def to_api_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def to_api_dict(self) -> dict:
        d: dict = {"role": self.role}
        if self.role == "tool":
            d["tool_call_id"] = self.tool_call_id
            d["name"] = self.name
            d["content"] = self.content
            return d
        d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [tc.to_api_dict() for tc in self.tool_calls]
        return d


@dataclass
class Response:
    content: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    raw: dict = field(default_factory=dict)
```

**Step 4: 跑测试 → 通过**

**Step 5: 提交**

```bash
git add src/my_agent/llm tests/unit/test_llm_types.py
git commit -m "feat(llm): internal Message/ToolCall/Response types"
```

---

## Task I0.2: LLMClient(mock 测试)

**Files:**
- Create: `src/my_agent/llm/client.py`
- Create: `tests/unit/test_llm_client.py`

**Step 1: 写测试(用 mocker 替换 openai)**

```python
# tests/unit/test_llm_client.py
from unittest.mock import MagicMock
from my_agent.llm.client import LLMClient
from my_agent.llm.types import Message


def make_fake_completion(text="hi", tool_calls=None, finish_reason="stop"):
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = tool_calls or []
    choice = MagicMock(message=msg, finish_reason=finish_reason)
    return MagicMock(choices=[choice])


def test_send_returns_text(mocker):
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = make_fake_completion("hello")

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    resp = client.send([Message(role="user", content="hi")], tools=[], max_tokens=100)

    assert resp.content == "hello"
    assert resp.finish_reason == "stop"
    assert resp.tool_calls == []


def test_send_passes_messages_to_api(mocker):
    fake_openai = mocker.patch("my_agent.llm.client.openai.OpenAI")
    fake_openai.return_value.chat.completions.create.return_value = make_fake_completion()

    client = LLMClient(api_key="k", base_url="https://x", model="qwen-plus")
    client.send([Message(role="user", content="hi")], tools=[], max_tokens=100)

    call_kwargs = fake_openai.return_value.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "qwen-plus"
    assert call_kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert call_kwargs["max_tokens"] == 100
```

**Step 2: 跑测试 → 失败**

**Step 3: 实现**

```python
# src/my_agent/llm/client.py
import openai
from .types import Message, Response, ToolCall


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def send(
        self,
        messages: list[Message],
        tools: list[dict],
        max_tokens: int,
    ) -> Response:
        kwargs = {
            "model": self.model,
            "messages": [m.to_api_dict() for m in messages],
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        completion = self.client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        msg = choice.message
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments)
            for tc in (msg.tool_calls or [])
        ]
        return Response(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            raw=completion.model_dump() if hasattr(completion, "model_dump") else {},
        )
```

**Step 4: 跑测试 → 通过**

**Step 5: 提交**

```bash
git add src/my_agent/llm/client.py tests/unit/test_llm_client.py
git commit -m "feat(llm): LLMClient wraps openai SDK"
```

---

## Task I0.3: 最小 CLI 入口

**Files:**
- Create: `src/my_agent/cli/__init__.py`(空)
- Create: `src/my_agent/cli/main.py`
- Create: `src/my_agent/__main__.py`

**Step 1: 写实现**(此版本极简,没有 REPL,只接受单条输入)

```python
# src/my_agent/cli/main.py
import sys
from my_agent.config import load_config
from my_agent.llm.client import LLMClient
from my_agent.llm.types import Message


def app(prompt: str | None = None) -> int:
    if prompt is None:
        prompt = " ".join(sys.argv[1:]) or input(">>> ")
    cfg = load_config()
    client = LLMClient(api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model)
    messages = [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content=prompt),
    ]
    resp = client.send(messages, tools=[], max_tokens=cfg.max_tokens)
    print(resp.content or "")
    return 0


if __name__ == "__main__":
    sys.exit(app())
```

```python
# src/my_agent/__main__.py
from my_agent.cli.main import app
import sys
sys.exit(app())
```

**Step 2: 集成测试(真打 API,可选)**

`tests/integration/test_iter0_smoke.py`:
```python
import os
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="no API key")
def test_minimal_chat():
    from my_agent.config import load_config
    from my_agent.llm.client import LLMClient
    from my_agent.llm.types import Message

    cfg = load_config()
    client = LLMClient(api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model)
    resp = client.send(
        [Message(role="user", content="只回复 OK 两个字符,不要别的")],
        tools=[],
        max_tokens=10,
    )
    assert resp.content
    assert resp.finish_reason in ("stop", "length")
```

**Step 3: 手动 demo**

把 `.env.example` 复制成 `.env`,填入真实 `DASHSCOPE_API_KEY`,然后:

```bash
python -m my_agent "用一句话介绍你自己"
```

Expected: 看到 Qwen 的回复。

**Step 4: 跑集成测试**

```bash
pytest -m integration tests/integration/ -v
```

Expected: PASS(或 SKIP 如果未配 key)。

**Step 5: 提交并打 tag**

```bash
git add src/my_agent/cli src/my_agent/__main__.py tests/integration
git commit -m "feat(iter0): minimal one-shot chat via CLI"
git tag v0.0 -m "Iter 0: minimal chat loop"
```

**Step 6: 写 retro**

`docs/notes/iter-0-retro.md`:简单记下:
- 跑通用了多久
- OpenAI 兼容模式有没有踩坑
- 对 Chat Completions 协议的理解(role / messages / max_tokens / finish_reason 各是什么含义)

---

# Phase 2: Iter 1 — 加 tool use(单工具单回合)

**目标:** 注册 `read_file` 工具,模型决定调用 → harness 分发 → 把结果回灌 → 拿到最终回复。**只支持一次 tool_calls 回合**(不循环)。
**验收:** `python -m my_agent "读一下 README.md 然后告诉我项目叫什么"` 输出包含 README 标题的回答。
**Git tag:** `v0.1`
**配套阅读:**
- OpenAI Function Calling 指南(完整看完 — 包括 parallel tool calls 部分)

---

## Task I1.1: Tool 抽象 + Registry

**Files:**
- Create: `src/my_agent/tools/__init__.py`
- Create: `src/my_agent/tools/base.py`
- Create: `tests/unit/test_tools_base.py`

**Step 1: 写测试**

```python
import pytest
from my_agent.tools.base import Tool, ToolRegistry, ToolResult


def echo(args: dict) -> str:
    return args["x"]


def test_registry_register_and_dispatch():
    reg = ToolRegistry()
    reg.register(Tool(
        name="echo",
        description="echo input",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        fn=echo,
    ))
    res = reg.dispatch("echo", '{"x":"hello"}')
    assert res.content == "hello"
    assert res.is_error is False


def test_registry_dispatch_unknown_tool():
    reg = ToolRegistry()
    res = reg.dispatch("nope", "{}")
    assert res.is_error is True
    assert "unknown" in res.content.lower()


def test_registry_dispatch_invalid_json():
    reg = ToolRegistry()
    reg.register(Tool(name="echo", description="", parameters={}, fn=echo))
    res = reg.dispatch("echo", "{not json")
    assert res.is_error is True
    assert "json" in res.content.lower()


def test_registry_dispatch_fn_raises():
    def boom(args): raise ValueError("kaboom")
    reg = ToolRegistry()
    reg.register(Tool(name="boom", description="", parameters={}, fn=boom))
    res = reg.dispatch("boom", "{}")
    assert res.is_error is True
    assert "kaboom" in res.content


def test_registry_get_schemas():
    reg = ToolRegistry()
    reg.register(Tool(
        name="echo",
        description="echo input",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
        fn=echo,
    ))
    schemas = reg.get_schemas()
    assert schemas == [{
        "type": "function",
        "function": {
            "name": "echo",
            "description": "echo input",
            "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
        },
    }]
```

**Step 2: 跑测试 → 失败**

**Step 3: 实现**

```python
# src/my_agent/tools/base.py
import json
from dataclasses import dataclass
from typing import Callable


@dataclass
class ToolResult:
    content: str
    is_error: bool = False


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[[dict], str]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def dispatch(self, name: str, args_json: str) -> ToolResult:
        if name not in self._tools:
            return ToolResult(content=f"unknown tool: {name}", is_error=True)
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError as e:
            return ToolResult(content=f"invalid JSON arguments: {e}", is_error=True)
        try:
            output = self._tools[name].fn(args)
            return ToolResult(content=str(output), is_error=False)
        except Exception as e:
            return ToolResult(content=f"{type(e).__name__}: {e}", is_error=True)
```

**Step 4: 跑测试 → 通过**

**Step 5: 提交**

```bash
git add src/my_agent/tools tests/unit/test_tools_base.py
git commit -m "feat(tools): Tool/ToolRegistry with safe dispatch"
```

---

## Task I1.2: read_file 工具

**Files:**
- Create: `src/my_agent/tools/files.py`
- Create: `tests/unit/test_tools_files.py`

**Step 1: 写测试**

```python
import pytest
from my_agent.tools.files import read_file_tool


def test_read_file_ok(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello")
    out = read_file_tool.fn({"path": str(p)})
    assert out == "hello"


def test_read_file_missing():
    with pytest.raises(FileNotFoundError):
        read_file_tool.fn({"path": "/nonexistent/xyz"})


def test_read_file_schema():
    s = read_file_tool.parameters
    assert s["type"] == "object"
    assert "path" in s["properties"]
    assert "path" in s["required"]
```

**Step 2: 跑测试 → 失败**

**Step 3: 实现**

```python
# src/my_agent/tools/files.py
from pathlib import Path
from .base import Tool


def _read_file(args: dict) -> str:
    return Path(args["path"]).read_text(encoding="utf-8")


read_file_tool = Tool(
    name="read_file",
    description="Read a UTF-8 text file from the local filesystem and return its contents.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path"}
        },
        "required": ["path"],
    },
    fn=_read_file,
)
```

**Step 4: 跑测试 → 通过**

**Step 5: 提交**

```bash
git add src/my_agent/tools/files.py tests/unit/test_tools_files.py
git commit -m "feat(tools): add read_file tool"
```

---

## Task I1.3: Conversation(基础版)

**Files:**
- Create: `src/my_agent/agent/__init__.py`
- Create: `src/my_agent/agent/conversation.py`
- Create: `tests/unit/test_conversation.py`

**Step 1: 写测试**

```python
from my_agent.agent.conversation import Conversation
from my_agent.llm.types import ToolCall


def test_append_and_serialize():
    c = Conversation(system="you are helpful")
    c.append_user("hi")
    c.append_assistant(content="hello")
    api = c.to_api_format()
    assert api[0] == {"role": "system", "content": "you are helpful"}
    assert api[1] == {"role": "user", "content": "hi"}
    assert api[2]["role"] == "assistant"
    assert api[2]["content"] == "hello"


def test_assistant_with_tool_calls():
    c = Conversation(system="s")
    c.append_user("u")
    c.append_assistant(content=None, tool_calls=[ToolCall(id="c1", name="read_file", arguments='{}')])
    c.append_tool_result(tool_call_id="c1", name="read_file", content="data")
    api = c.to_api_format()
    assert api[2]["tool_calls"][0]["id"] == "c1"
    assert api[3]["role"] == "tool"
    assert api[3]["tool_call_id"] == "c1"
    assert api[3]["content"] == "data"
```

**Step 2: 跑测试 → 失败**

**Step 3: 实现**

```python
# src/my_agent/agent/conversation.py
from my_agent.llm.types import Message, ToolCall


class Conversation:
    def __init__(self, system: str):
        self.system = system
        self.messages: list[Message] = [Message(role="system", content=system)]

    def append_user(self, text: str) -> None:
        self.messages.append(Message(role="user", content=text))

    def append_assistant(self, content: str | None, tool_calls: list[ToolCall] | None = None) -> None:
        self.messages.append(Message(role="assistant", content=content, tool_calls=tool_calls))

    def append_tool_result(self, tool_call_id: str, name: str, content: str) -> None:
        self.messages.append(Message(
            role="tool", tool_call_id=tool_call_id, name=name, content=content
        ))

    def to_api_format(self) -> list[dict]:
        return [m.to_api_dict() for m in self.messages]
```

**Step 4: 跑测试 → 通过**

**Step 5: 提交**

```bash
git add src/my_agent/agent tests/unit/test_conversation.py
git commit -m "feat(agent): Conversation history with tool message support"
```

---

## Task I1.4: 一回合 agent loop(无循环)+ wire up CLI

**Files:**
- Modify: `src/my_agent/cli/main.py`
- Create: `tests/unit/test_cli_iter1.py`

**Step 1: 写测试(全程 mock LLM)**

```python
from unittest.mock import MagicMock
from my_agent.cli.main import run_once
from my_agent.llm.types import Response, ToolCall


def test_single_tool_round(mocker, tmp_path):
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
    out = run_once(fake_client, prompt=f"读 {p} 告诉我项目名")
    assert "my-agent" in out
    assert fake_client.send.call_count == 2
```

**Step 2: 跑测试 → 失败**

**Step 3: 改 cli/main.py**

```python
# src/my_agent/cli/main.py
import sys
from my_agent.config import load_config
from my_agent.llm.client import LLMClient
from my_agent.tools.base import ToolRegistry
from my_agent.tools.files import read_file_tool
from my_agent.agent.conversation import Conversation


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(read_file_tool)
    return reg


def run_once(client, prompt: str, system: str = "You are a helpful assistant.") -> str:
    """Run at most one tool round (Iter 1 contract)."""
    registry = build_registry()
    conv = Conversation(system=system)
    conv.append_user(prompt)

    # Round 1
    resp = client.send(conv.messages, tools=registry.get_schemas(), max_tokens=4096)
    conv.append_assistant(content=resp.content, tool_calls=resp.tool_calls or None)

    if resp.finish_reason == "stop":
        return resp.content or ""

    # Dispatch tool calls
    for tc in resp.tool_calls:
        result = registry.dispatch(tc.name, tc.arguments)
        conv.append_tool_result(tc.id, tc.name, result.content)

    # Round 2: final
    resp2 = client.send(conv.messages, tools=registry.get_schemas(), max_tokens=4096)
    conv.append_assistant(content=resp2.content)
    return resp2.content or ""


def app() -> int:
    cfg = load_config()
    client = LLMClient(api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model)
    prompt = " ".join(sys.argv[1:]) or input(">>> ")
    print(run_once(client, prompt))
    return 0


if __name__ == "__main__":
    sys.exit(app())
```

**Step 4: 跑测试 → 通过**

**Step 5: 集成 demo**

```bash
python -m my_agent "读一下 README.md,然后告诉我项目叫什么"
```

Expected: 模型先调 read_file 再回答 "my-agent"。

**Step 6: 提交并打 tag**

```bash
git add src/my_agent/cli/main.py tests/unit/test_cli_iter1.py
git commit -m "feat(iter1): single-round tool use with read_file"
git tag v0.1 -m "Iter 1: single tool round"
```

**Step 7: retro**

`docs/notes/iter-1-retro.md`:把 OpenAI 协议里 tool_calls / tool_call_id 配对、parallel tool calls 的概念、`arguments` 是字符串这件事 写到自己能讲清楚的程度。

---

# Phase 3: Iter 2 — 多轮 agent loop

**目标:** 把 Iter 1 的"两次 send"泛化成 while 循环,直到 `finish_reason == "stop"` 或达到 `max_iterations`。
**验收:** `python -m my_agent "读 README.md 后写一份 docs/about.md 简介"` — 这需要至少 2 个工具调用回合(read 然后 write)。
**Git tag:** `v0.2`
**配套阅读:**
- ReAct: Synergizing Reasoning and Acting in Language Models(Yao et al., 2022, arXiv:2210.03629)
- 重点理解:thought-action-observation 循环 与 OpenAI 协议的对应关系

---

## Task I2.1: write_file 工具(为多轮场景做准备)

**Files:**
- Modify: `src/my_agent/tools/files.py`
- Modify: `tests/unit/test_tools_files.py`

**Step 1: 加测试**

```python
def test_write_file_creates(tmp_path):
    from my_agent.tools.files import write_file_tool
    target = tmp_path / "out.md"
    out = write_file_tool.fn({"path": str(target), "content": "hello"})
    assert "wrote" in out.lower()
    assert target.read_text() == "hello"


def test_write_file_overwrites(tmp_path):
    from my_agent.tools.files import write_file_tool
    target = tmp_path / "out.md"
    target.write_text("old")
    write_file_tool.fn({"path": str(target), "content": "new"})
    assert target.read_text() == "new"
```

**Step 2: 跑测试 → 失败**

**Step 3: 实现**

```python
# 追加到 src/my_agent/tools/files.py
def _write_file(args: dict) -> str:
    p = Path(args["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args["content"], encoding="utf-8")
    return f"wrote {len(args['content'])} bytes to {p}"


write_file_tool = Tool(
    name="write_file",
    description="Write text content to a file. Creates parent directories if needed. Overwrites existing files.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    fn=_write_file,
)
```

**Step 4: 跑测试 → 通过**

**Step 5: 提交**

```bash
git add src/my_agent/tools/files.py tests/unit/test_tools_files.py
git commit -m "feat(tools): add write_file"
```

---

## Task I2.2: AgentLoop + errors 模块

**Files:**
- Create: `src/my_agent/agent/errors.py`
- Create: `src/my_agent/agent/loop.py`
- Create: `tests/unit/test_agent_loop.py`

**Step 1: 写测试**

```python
from unittest.mock import MagicMock
import pytest
from my_agent.agent.loop import AgentLoop
from my_agent.agent.conversation import Conversation
from my_agent.agent.errors import AgentBudgetExceeded
from my_agent.tools.base import ToolRegistry, Tool
from my_agent.llm.types import Response, ToolCall


@pytest.fixture
def echo_registry():
    reg = ToolRegistry()
    reg.register(Tool(
        name="echo", description="echo", parameters={}, fn=lambda a: a.get("x", "")
    ))
    return reg


def test_loop_stops_immediately(echo_registry):
    client = MagicMock()
    client.send.return_value = Response(content="hi", tool_calls=[], finish_reason="stop")
    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    out = loop.run_turn(Conversation(system="s"), "hello")
    assert out == "hi"
    assert client.send.call_count == 1


def test_loop_runs_two_tool_rounds(echo_registry):
    client = MagicMock()
    client.send.side_effect = [
        Response(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments='{"x":"1"}')], finish_reason="tool_calls"),
        Response(content=None, tool_calls=[ToolCall(id="c2", name="echo", arguments='{"x":"2"}')], finish_reason="tool_calls"),
        Response(content="done", tool_calls=[], finish_reason="stop"),
    ]
    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    out = loop.run_turn(Conversation(system="s"), "go")
    assert out == "done"
    assert client.send.call_count == 3


def test_loop_budget_exceeded(echo_registry):
    client = MagicMock()
    client.send.return_value = Response(
        content=None,
        tool_calls=[ToolCall(id="c", name="echo", arguments='{"x":"x"}')],
        finish_reason="tool_calls",
    )
    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=3)
    with pytest.raises(AgentBudgetExceeded):
        loop.run_turn(Conversation(system="s"), "go")


def test_loop_handles_parallel_tool_calls(echo_registry):
    client = MagicMock()
    client.send.side_effect = [
        Response(
            content=None,
            tool_calls=[
                ToolCall(id="c1", name="echo", arguments='{"x":"a"}'),
                ToolCall(id="c2", name="echo", arguments='{"x":"b"}'),
            ],
            finish_reason="tool_calls",
        ),
        Response(content="ok", tool_calls=[], finish_reason="stop"),
    ]
    loop = AgentLoop(client=client, tools=echo_registry, max_iterations=5)
    out = loop.run_turn(Conversation(system="s"), "go")
    assert out == "ok"
    # second send should see two tool messages
    second_call_msgs = client.send.call_args_list[1].args[0]
    tool_msgs = [m for m in second_call_msgs if m.role == "tool"]
    assert len(tool_msgs) == 2
```

**Step 2: 跑测试 → 失败**

**Step 3: 实现 errors**

```python
# src/my_agent/agent/errors.py
class AgentError(Exception):
    """Base for all agent errors"""


class AgentBudgetExceeded(AgentError):
    """Hit max_iterations without finish_reason=stop"""
```

**Step 4: 实现 loop**

```python
# src/my_agent/agent/loop.py
from my_agent.agent.conversation import Conversation
from my_agent.agent.errors import AgentBudgetExceeded
from my_agent.tools.base import ToolRegistry


class AgentLoop:
    def __init__(self, client, tools: ToolRegistry, max_iterations: int = 20, max_tokens: int = 4096):
        self.client = client
        self.tools = tools
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens

    def run_turn(self, conv: Conversation, user_input: str) -> str:
        conv.append_user(user_input)
        for _ in range(self.max_iterations):
            resp = self.client.send(
                conv.messages,
                tools=self.tools.get_schemas(),
                max_tokens=self.max_tokens,
            )
            conv.append_assistant(
                content=resp.content,
                tool_calls=resp.tool_calls or None,
            )
            if resp.finish_reason in ("stop", "length"):
                return resp.content or ""
            if resp.finish_reason == "tool_calls":
                for tc in resp.tool_calls:
                    result = self.tools.dispatch(tc.name, tc.arguments)
                    conv.append_tool_result(tc.id, tc.name, result.content)
                continue
            # unknown finish_reason -> bail
            return resp.content or ""
        raise AgentBudgetExceeded(f"exceeded {self.max_iterations} iterations")
```

**Step 5: 跑测试 → 通过**

**Step 6: 重构 cli/main.py 用 AgentLoop**

```python
# src/my_agent/cli/main.py
import sys
from my_agent.config import load_config
from my_agent.llm.client import LLMClient
from my_agent.tools.base import ToolRegistry
from my_agent.tools.files import read_file_tool, write_file_tool
from my_agent.agent.conversation import Conversation
from my_agent.agent.loop import AgentLoop


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(read_file_tool)
    reg.register(write_file_tool)
    return reg


def app() -> int:
    cfg = load_config()
    client = LLMClient(api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model)
    loop = AgentLoop(client=client, tools=build_registry())
    conv = Conversation(system="You are a helpful coding assistant. Use tools to read/write files when needed.")
    prompt = " ".join(sys.argv[1:]) or input(">>> ")
    print(loop.run_turn(conv, prompt))
    return 0


if __name__ == "__main__":
    sys.exit(app())
```

删除 `run_once` 和它的测试(已被 AgentLoop 取代)。

**Step 7: 跑全部单测**

```bash
pytest -v
```

Expected: 全部 PASS。

**Step 8: 集成 demo**

```bash
python -m my_agent "读 README.md,然后写一份 200 字的项目简介到 docs/about.md"
```

Expected: 文件被创建,内容合理。

**Step 9: 提交并打 tag**

```bash
git add -A
git commit -m "feat(iter2): generalize to multi-round agent loop"
git tag v0.2 -m "Iter 2: full agent loop"
```

**Step 10: retro**

`docs/notes/iter-2-retro.md`:对照 ReAct 论文画一张图,标注 thought / action / observation 在 OpenAI 协议下分别由谁承担(answer: thought 隐含在 assistant.content,action = tool_calls,observation = tool message)。

---

# Phase 4: Iter 3 — 流式输出 + run_bash

**目标:** 切到 `stream=True`,边生成边打印;新增 `run_bash` 工具(带 timeout、cwd 限制)。
**验收:** 在终端能看到逐 token 打印;能执行 `ls`、`pytest` 等命令。
**Git tag:** `v0.3`
**工期:** ~3 天 (流式解析最容易踩坑)

**配套阅读:**
- OpenAI streaming 章节(完整看 — 尤其 chunk delta 累积、tool_calls.index 这一段)
- subprocess 文档:Popen vs run、timeout 行为

**关键契约:**

```python
# LLMClient 新增方法
def stream(self, messages, tools, max_tokens) -> Iterator[StreamEvent]:
    """yield 文本增量、工具调用增量、最终 finish_reason"""
```

`StreamEvent` 类型:
```python
StreamEvent = TextDelta(text: str)
            | ToolCallDelta(index: int, id: str | None, name: str | None, arguments_delta: str)
            | FinishEvent(finish_reason: str)
```

AgentLoop 增加 `run_turn_stream(conv, user_input) -> Iterator[str]` — yield 用户可见的文本碎片。

`run_bash` 工具:
```python
parameters = {
    "type": "object",
    "properties": {
        "command": {"type": "string"},
        "timeout": {"type": "integer", "default": 30},
    },
    "required": ["command"],
}
# fn 执行 subprocess.run(shell=True, timeout=..., cwd=PROJECT_ROOT, capture_output=True)
# 返回 stdout + stderr + exit_code 拼接的字符串
```

**关键测试场景:**
1. text 流式累积 — 多 chunk 合并后等于完整 content
2. tool_calls 流式累积 — `arguments` 是碎片化字符串,要按 `index` 拼接(用录制的 fixture)
3. run_bash 超时 → ToolResult(is_error=True)
4. run_bash cwd 不能跳出项目根

**写一个 `tests/fixtures/streaming/`** 目录,把一次真实 streaming 调用的 chunk 列表存成 JSON,便于离线测试。

**任务清单(粒度同 Iter 0-2):**
- I3.1 LLMClient.stream + StreamEvent 类型 + 录制 fixture + 测试
- I3.2 AgentLoop.run_turn_stream
- I3.3 run_bash 工具 + sandbox 测试
- I3.4 CLI 切到流式打印 + ctrl-c 中断
- I3.5 retro

> **建议:** 进入 Iter 3 前重新调一次 `writing-plans` 把这 5 个任务展开成 bite-sized TDD 步骤,流式解析的边界情况比想象中多。

---

# Phase 5: Iter 4 — REPL + 命令解析

**目标:** 持久化交互模式,支持 slash 命令。
**验收:** 输入 `>>> ` 提示符可多轮对话;`/reset` 清历史;`/save FILE` 存当前会话;`/load FILE` 恢复;`/quit` 退出;ctrl-c 中断当前 turn 但不退出 REPL。
**Git tag:** `v0.4`
**工期:** ~2 天

**关键依赖:** `typer` + `rich`(替换裸 print)

**关键契约:**
- `cli.repl.Repl(loop, conv)` 持有一个 AgentLoop 实例 + 一个长期 Conversation
- 命令分发用 dict: `{"reset": cmd_reset, "save": cmd_save, ...}`
- `/save` 序列化 `conv.messages` 到 JSON;`/load` 反序列化(注意 dataclass 重建)
- ctrl-c:在 `loop.run_turn` 外层 `try/except KeyboardInterrupt`,设置 `conv.rollback()` 删除最后一条 user 消息

**任务清单:**
- I4.1 Conversation.save / load + 测试
- I4.2 Repl 主循环 + 命令分发
- I4.3 ctrl-c 优雅处理
- I4.4 rich 渲染:Markdown / 流式着色 / 工具调用折叠面板
- I4.5 retro

---

# Phase 6: Iter 5 — 上下文管理

**目标:** 监控 token 数,超限时压缩。
**验收:** 跑一个故意长的对话(让模型生成大段文本),观察到 ContextManager 自动压缩,后续对话仍连贯。
**Git tag:** `v0.5`
**工期:** ~3 天

**配套阅读:**
- Anthropic Engineering: "Long context: prompt engineering and pitfalls"
- OpenAI cookbook: token counting & summarization patterns

**关键契约:**
```python
class ContextManager:
    def __init__(self, budget: int, summarize_client): ...

    def estimate(self, messages: list[Message]) -> int:
        # 用 tiktoken 估算(或 anthropic 的 count_tokens API)
        ...

    def maybe_compact(self, conv: Conversation) -> bool:
        # 返回是否做了压缩
        # 策略:超 budget 时,把 [system] 后到倒数第 K 轮之前的所有消息
        # 调用 summarize_client 生成一句 summary,替换为单条 system 风格的 user/assistant 对
        ...
```

**任务清单:**
- I5.1 token 估算实现 + 测试(用 tiktoken,默认编码 cl100k_base / o200k_base)
- I5.2 sliding window 压缩策略 + 单测(mock 压缩 LLM)
- I5.3 接入 AgentLoop:每次 send 前 maybe_compact
- I5.4 集成测试:故意长 prompt 触发压缩
- I5.5 retro:对比 buffer / summary / vector 三种记忆策略,记笔记

---

# Phase 7: Iter 6 — Web 工具

**目标:** 加 `web_fetch`(用 httpx) 与 `web_search`(选一个搜索 API:tavily / brave / serper)。
**验收:** 问 "今天的 hacker news 头条" 能正确通过搜索 + 抓取得到答案。
**Git tag:** `v0.6`
**工期:** ~2 天

**关键契约:**
- `web_fetch(url, max_chars=8000)`:httpx 拉网页,trafilatura/readability 提取正文,截断
- `web_search(query, top_k=5)`:调外部搜索 API,返回 `[{title, url, snippet}, ...]`

**新增依赖:** `httpx`, `trafilatura`(或 `readability-lxml`), `tavily-python`(或所选搜索厂商 SDK)

**任务清单:** I6.1-I6.4(自行细化)

---

# Phase 8: Iter 7 — 跨会话记忆

**目标:** 项目级记忆文件(类 CLAUDE.md)+ 长期 memory 文件夹。
**验收:** 在一次会话告诉 agent "我用 vim",换一次新会话,agent 记得。
**Git tag:** `v0.7`
**工期:** ~3 天

**配套阅读:** "MemGPT: Towards LLMs as Operating Systems"(Packer et al., 2023)+ Anthropic 关于 memory 的工程博客

**关键契约:**
- 启动时自动加载 `./AGENT.md`(项目级,git tracked)和 `~/.my-agent/memory/MEMORY.md`(用户级)拼到 system prompt
- 新增 `remember(category, content)` 工具:让 LLM 主动写记忆
- 记忆文件结构参照 Claude Code memory(YAML frontmatter + body + index)

**任务清单:** I7.1-I7.5

---

# Phase 9: Iter 8 — MCP 客户端

**目标:** 接入 MCP 协议,可连第三方 server(如 filesystem / playwright / github)。
**验收:** `python -m my_agent --mcp-config mcp.json` 启动后,`tools/list` 自动包含外部 server 的工具,可被 LLM 调用。
**Git tag:** `v0.8`
**工期:** ~3 天

**配套阅读:** MCP 协议 spec(完整通读)+ 至少一个开源 MCP server 的源码(推荐 `@modelcontextprotocol/server-filesystem`)

**关键契约:**
- 新依赖:`mcp` Python SDK
- `mcp_config.json` schema:`{servers: [{name, command, args, env}]}`
- 启动时 spawn 每个 MCP server,通过 stdio 通信
- `MCPToolAdapter` 把 MCP tool 包装成内部 `Tool` 类型,注册到 `ToolRegistry`

**任务清单:** I8.1-I8.6

---

# Phase 10: Iter 9 — Sub-agent / Task tool

**目标:** 加 `task` 工具,可派生子 agent 处理独立子任务,主 agent 拿到子 agent 总结(不污染主上下文)。
**验收:** 一个长任务被自动拆为子任务,主对话历史保持简洁。
**Git tag:** `v0.9`
**工期:** ~3 天

**配套阅读:** Reflexion (Shinn et al. 2023) + AutoGPT 架构概述 + Claude Code 的 sub-agent 模式

**关键契约:**
- `task(description, subagent_type) -> str` 工具
- 子 agent 是同一 `AgentLoop` 类的新实例,新 Conversation,继承 ToolRegistry
- 子 agent 完成后只返回 final text 给父级
- 加入 `agent_id` 透传(为日后 multi-agent observability 铺路)

**任务清单:** I9.1-I9.5

---

# Phase 11: Iter 10 — Web/API 包装

**目标:** FastAPI 暴露 `/chat` (SSE 流式) endpoint,可用浏览器或脚本调用。
**验收:** 浏览器打开 `http://localhost:8000` 看到极简聊天页;`curl -N http://localhost:8000/chat -d '{"prompt":"hi"}'` 看到流式返回。
**Git tag:** `v1.0`
**工期:** ~2 天

**关键契约:**
- 新依赖:`fastapi`, `uvicorn`, `sse-starlette`
- 后端复用 `AgentLoop`;每个 SSE 连接 = 一个 Conversation
- 极简前端:单文件 HTML + vanilla JS 处理 EventSource
- v0 不做认证(本地用),后续如要分享再加

**任务清单:** I10.1-I10.4

---

# 全局约定与质量基线

## Git 工作流
- 每个 iter 单独 git tag(`v0.0`–`v1.0`)
- 任务粒度提交:每个 task 一个 commit,描述清晰("feat(iter2): ...")
- main 始终保持可运行;实验性改动开 `iter-N-spike` 分支

## 测试基线
- 单测:`pytest`,目标 < 5 秒跑完
- 集成测试:`pytest -m integration` 显式启用
- 引入新模块时,**先写测试 + 看到失败 + 再写实现**(TDD 强制)

## 文档基线
- 每个 iter 完成写 `docs/notes/iter-N-retro.md`(200 字内,记踩的坑 + 学到的概念)
- `README.md` 跟随 iter 同步更新功能矩阵
- API 不稳定的内部模块加 `# UNSTABLE: ...` 注释

## 学习节奏检查
进入 Iter K 之前,问自己三个问题:
1. 我能在不看代码的情况下,讲清楚 Iter K-1 的核心机制吗?
2. 我有没有跳过配套阅读?(跳过的话,补回来再开新 iter)
3. 我能预测 Iter K 的核心难点是什么吗?

如果三个里有一个答不上,先回去补。

---

# 执行说明

**当前位置:** Phase 0 + Iter 0-2 已细化到 bite-sized;Iter 3-10 给了 milestone 和契约。

**进入 Iter 3 时建议:** 重新 invoke `writing-plans`,只针对 Iter 3 拆出 bite-sized 任务,届时已有 v0.2 真实代码作为更精确的上下文。

**首次执行入口:** Phase 0 Task 0.1。

---

## Plan complete and saved to `docs/plans/2026-05-15-my-agent-implementation-plan.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch fresh subagent per task, review between tasks, fast iteration. 适合你想边看 agent 干活边学的情况。

**2. Parallel Session (separate)** — Open new session with `executing-plans`, batch execution with checkpoints. 适合你想自己亲手敲代码、把这个计划当 guide 用的情况(**强烈推荐这个 — 学习目标决定了你应该亲手写,不是看 agent 写**)。

**3. 自己手敲,我作答疑** — 你按计划自己实现,卡住时随时问我。这是上面两个的延伸,也是最贴合你"深入学习"目标的玩法。

**选哪种?**
