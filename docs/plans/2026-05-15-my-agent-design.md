# my-agent 设计文档

**日期:** 2026-05-15
**状态:** 已确认,进入实现计划阶段

## 目标

从 0 搭建一个自用的通用 agent,在搭建过程中深入学习 agent 开发知识。

## 关键决策

| 维度 | 选择 | 理由 |
|---|---|---|
| 语言 | Python | AI 生态最丰富,文档/示例最多 |
| 基座 | 裸写 OpenAI 兼容 API + 自造 harness | 不用 Agent SDK / LangChain,确保学到底层 |
| 主用模型 | Qwen(走 DashScope OpenAI 兼容模式) | 开发期便宜,工具调用稳定 |
| 协议风格 | OpenAI 原生格式 | Qwen/DeepSeek/GLM/Kimi/GPT 通吃,无需翻译层 |
| 用途 | 通用助手(code + docs + web + life) | |
| 交互形态 | CLI 优先,后期加 web/API | 学习曲线平缓,调试方便 |
| 记忆 | v0 会话级,跨会话后期加 | 先聚焦 agent loop + tool use |
| 工具扩展 | v0 内置工具,v1 接 MCP | 分阶段,避免起点过高 |
| 学习节奏 | 边写边学,关键节点补论文/文档 | 平衡产出与理论 |

## 实施路径:垂直切片 / 渐进闭环

每个 iteration 都交付一个端到端可用的 agent。

| Iter | 目标 | 配套阅读 | 工期估算 |
|---|---|---|---|
| 0 | 最小 chat loop:一次 API 调用,终端打印 | OpenAI Chat Completions 文档 | ~1 天 |
| 1 | 加 tool use:1 个工具(read_file) | OpenAI Function Calling 文档 | ~2 天 |
| 2 | 加 agent loop:多轮 tool 调用直到 finish_reason=stop | ReAct 论文(Yao et al. 2022) | ~2 天 |
| 3 | 加流式输出 + 多工具 (write_file/run_bash) | OpenAI streaming 文档 | ~3 天 |
| 4 | 加 REPL + 命令解析(/reset、/save、ctrl-c) | — | ~2 天 |
| 5 | 加上下文管理:token 预算、压缩 | Anthropic context mgmt 工程博客 | ~3 天 |
| 6 | 加 web 工具 + 搜索(web_fetch / web_search) | — | ~2 天 |
| 7 | 加跨会话记忆(类 CLAUDE.md + memory 文件) | Memory in LLM agents 综述 | ~3 天 |
| 8 | 接 MCP 客户端(连第三方 server) | MCP 协议 spec | ~3 天 |
| 9 | 加 sub-agent(Task tool,可派生子 agent) | Reflexion / Multi-agent 论文摘要 | ~3 天 |
| 10 | 加 web/API 包装(FastAPI + SSE) | — | ~2 天 |

## 总体架构(Iter 5 时的稳定形态)

```
              ┌──────────────────────────────┐
              │    CLI / REPL  (Typer+Rich)   │   ← cli/main.py
              └──────────────┬───────────────┘
                             │ user_input
                             ▼
              ┌──────────────────────────────┐
              │        Agent Loop             │   ← agent/loop.py
              │  while not done:              │
              │    resp = client.send(...)    │
              │    if tool_calls: dispatch    │
              │    if stop:       break       │
              └──┬─────────┬──────────┬──────┘
                 │         │          │
                 ▼         ▼          ▼
         ┌──────────┐ ┌──────────┐ ┌──────────────┐
         │Conversa- │ │  Tool    │ │   Context    │
         │  tion    │ │ Registry │ │   Manager    │
         │(history) │ │(name→fn) │ │(budget,trim) │
         └──────────┘ └────┬─────┘ └──────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Tools/*.py  │
                    │ read_file    │
                    │ write_file   │
                    │ run_bash     │
                    │ web_fetch    │
                    └─────────────┘
```

## 目录结构(初版)

```
my-agent/
├── pyproject.toml
├── README.md
├── .env.example                  # DASHSCOPE_API_KEY / ANTHROPIC_API_KEY
├── src/
│   └── my_agent/
│       ├── __init__.py
│       ├── cli/
│       │   └── main.py           # 入口:python -m my_agent
│       ├── agent/
│       │   ├── loop.py           # 核心 agent 循环
│       │   ├── conversation.py   # 消息历史 + validate()
│       │   ├── context.py        # 上下文/token 管理
│       │   └── errors.py         # 自定义异常
│       ├── tools/
│       │   ├── base.py           # Tool 类 + Registry
│       │   ├── files.py          # read_file / write_file
│       │   ├── shell.py          # run_bash
│       │   └── web.py            # web_fetch / web_search
│       ├── llm/
│       │   ├── types.py          # Message / ToolCall / Response
│       │   └── client.py         # OpenAI SDK 包装
│       └── config.py             # provider 切换、模型、token 预算
├── tests/
│   ├── unit/
│   ├── integration/              # 真打 API,默认 skip
│   ├── fixtures/                 # 示例文件 / 录制响应
│   └── conftest.py
└── docs/
    ├── plans/                    # design / 实施计划(本文档所在)
    └── notes/                    # 学习笔记(论文摘要、坑点)
```

## 核心组件

### LLMClient

```python
class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str): ...
    def send(self, messages, tools, max_tokens) -> Response: ...
```

- 走 OpenAI 兼容模式,内部 `openai.OpenAI(base_url=...)`
- 默认 base_url:`https://dashscope.aliyuncs.com/compatible-mode/v1`
- 内置 retry(3 次,指数退避)
- v0 非流式;Iter 3 加流式分支

### Message / ToolCall(内部数据模型)

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str        # 注意:OpenAI 是 JSON 字符串

@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None
    tool_calls: list[ToolCall] | None = None   # 仅 assistant
    tool_call_id: str | None = None            # 仅 role=tool
    name: str | None = None                    # 仅 role=tool
```

### Tool / ToolRegistry

```python
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict             # JSON Schema
    fn: Callable[[dict], str]

class ToolRegistry:
    def register(self, tool: Tool) -> None: ...
    def get_schemas(self) -> list[dict]: ...
    def dispatch(self, name: str, args_json: str) -> ToolResult: ...
        # 内部 try/except:任何异常 → ToolResult(is_error=True)
```

### Conversation

```python
class Conversation:
    messages: list[Message]
    system: str

    def append_user(self, text: str): ...
    def append_assistant(self, content: str|None, tool_calls=None): ...
    def append_tool_result(self, tool_call_id: str, name: str, content: str): ...
    def to_api_format(self) -> list[dict]: ...
    def validate(self) -> None:
        """每次 send 前自检 4 条不变量,失败立即 raise(避免远端 400)"""
    def save(self, path: Path): ...
    def load(self, path: Path): ...
```

**4 条不变量:**
1. assistant.tool_calls 后必须紧跟同等数量的 tool message,顺序与 id 对齐
2. 每条 tool message 的 `tool_call_id` 必须能在前一条 assistant.tool_calls 找到
3. assistant.content 与 tool_calls 不能两个都为空
4. system 永远在 index 0,且只有一条

### ContextManager(Iter 5)

```python
class ContextManager:
    def __init__(self, budget: int, model: str): ...
    def estimate(self, conversation) -> int: ...
    def compact(self, conversation) -> Conversation:
        """超限时:保留 system + 最近 K 轮原文,中间换 LLM 总结"""
```

### AgentLoop

```python
class AgentLoop:
    def __init__(self, client, tools, conversation, context_mgr): ...
    def run_turn(self, user_input: str) -> str:
        """
        1. conversation.append_user(user_input)
        2. for _ in range(max_iterations):
             context_mgr.compact(conversation) if needed
             conversation.validate()
             resp = client.send(...)
             conversation.append_assistant(resp.content, resp.tool_calls)
             if resp.finish_reason == "stop": return resp.content
             if resp.finish_reason == "tool_calls":
                 for tc in resp.tool_calls:
                     result = tools.dispatch(tc.name, tc.arguments)
                     conversation.append_tool_result(tc.id, tc.name, result)
                 continue
        raise AgentBudgetExceeded
        """
```

## 数据流(典型一轮 turn)

详见设计讨论 §3。关键点:

1. user 输入追加 → send → 模型返 `finish_reason=tool_calls` + assistant.tool_calls
2. assistant 消息进历史 → 分发每个 tool_call → 每个 result 作为独立 `role=tool` 消息追加
3. 再次 send → 这次返 `finish_reason=stop` + assistant.content
4. 最终 content 给 CLI 打印,turn 结束

## 错误处理

| 层 | 抛异常? | 策略 |
|---|---|---|
| Tool 实现(`fn`) | 可以抛 | Registry 兜底 |
| ToolRegistry.dispatch | **不抛** | 异常 → `ToolResult(is_error=True, content=str(e))` |
| LLMClient.send | 可以抛 | retry 3 次处理 429/5xx;4xx schema 错误直抛 |
| AgentLoop.run_turn | 可以抛 | KeyboardInterrupt / AgentBudgetExceeded |
| CLI 主循环 | 兜底所有 | 打印友好错误,不退出 REPL |

## 测试策略

- **单元测试(80%):** pytest,mock LLMClient,< 5s 跑完
- **集成测试:** 真打 Qwen API,默认 skip,`pytest -m integration` 启用
- **录制重放(Iter 4+):** 用 vcrpy 或 fixtures 重放真实 API 响应,验证 streaming 解析

## 安全边界

1. `run_bash` 默认 sandbox:30s timeout,禁出项目目录
2. API key 永不入代码 / 日志,`.env` + redact
3. `write_file` 在陌生路径首次写入时回显确认

## 不做的事(YAGNI)

- 不做 Anthropic 多 provider 抽象(等真要切再加 Adapter)
- 不做 async tools(v0 全同步)
- 不做 Conversation v0 持久化(Iter 4 加 /save,Iter 7 上数据库)
- 不引入 LangChain / LlamaIndex / Agent SDK
- 不做权限模型 / 审计日志(等真有协作场景再加)
