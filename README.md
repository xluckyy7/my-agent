# my-agent

一个从 0 手写的 Python CLI 通用 agent —— **不用任何 agent 框架**(没有 LangChain / Agent SDK / OpenAI Assistants),直接调 OpenAI 兼容协议,自造 harness。**学习目标 + 自用目标**双驱动。

主用模型:**Qwen**(走 DashScope OpenAI 兼容端点);切 GPT / DeepSeek / GLM / Kimi 只需改 `base_url` + `model` + `key`。

---

## 快速上手

```bash
git clone <repo>
cd my-agent

# 准备虚拟环境 + 装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 配 API key
cp .env.example .env
# 然后编辑 .env 填入你的 DASHSCOPE_API_KEY
```

### 一次性提问

```bash
python -m my_agent "用一句话介绍你自己"
```

### 多轮 REPL

```bash
python -m my_agent
>>> 读 README.md 告诉我项目叫什么
[模型流式回答]
>>> /save sessions/today.json
saved 5 messages to sessions/today.json
>>> /quit
```

### 调试模式

```bash
MY_AGENT_DEBUG=1 python -m my_agent "你好"
# stderr 输出完整 REQUEST / RESPONSE / 每个 streaming chunk 的 JSON
```

---

## 当前功能(v0.4)

- **多轮对话** — REPL 模式跨 turn 持久 conversation
- **流式输出** — 文本逐 token 显示
- **工具调用** — agent 会自主调用工具,内置 `read_file` / `write_file` / `run_bash`
- **工具指示器** — 终端实时显示 `▸ tool {args}` → `✓ 0.12s {preview}` / `✗ error`
- **多轮 ReAct loop** — 工具调用可链式触发,直到任务完成(上限 20 轮)
- **会话持久化** — `/save <path>` 落 JSON,`/load <path>` 恢复
- **协议守护** — Conversation 5 条不变量校验,提前抓住 API 400 类问题
- **中文输入正常** — `readline` 处理多字节字符 + 方向键 + ↑↓ 历史

## 命令

| 命令 | 别名 | 说明 |
|---|---|---|
| `/help` | `/?` | 列出所有命令 |
| `/quit` | `/q` `/exit` | 退出 REPL |
| `/reset` | | 清历史,保留 system prompt |
| `/save <path>` | | 把当前 conversation 落 JSON |
| `/load <path>` | | 用文件中的 conversation 替换当前 |

**快捷键:**
- `ctrl-d`(EOF):立即退出
- `ctrl-c`(prompt 上):双击退出 / 单击清当前输入
- `ctrl-c`(turn 进行中):中断当前 turn,REPL 继续

---

## 架构

```
              ┌──────────────────────────────┐
              │   CLI / Repl(slash 命令)    │   cli/main.py + cli/repl.py
              └──────────────┬───────────────┘
                             │ user_input
                             ▼
              ┌──────────────────────────────┐
              │     AgentLoop.run_turn_stream │   agent/loop.py
              │  while not done:              │
              │    LLMClient.stream(...)      │
              │    assemble events            │
              │    if tool_calls: dispatch    │
              │    yield TurnEvent            │
              └──┬─────────┬──────────┬──────┘
                 │         │          │
                 ▼         ▼          ▼
         ┌──────────┐ ┌──────────┐ ┌──────────────┐
         │Conversa- │ │  Tool    │ │  LLMClient   │
         │  tion    │ │ Registry │ │  (openai SDK)│
         │+validate │ │name → fn │ │ + base_url   │
         └──────────┘ └────┬─────┘ └──────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  tools/*.py │
                    │ read_file   │
                    │ write_file  │
                    │ run_bash    │
                    └─────────────┘
```

**关键约定:**
- 内部消息模型用 **OpenAI 原生格式**(`role/content/tool_calls/tool_call_id`),不做翻译层
- LLM 流式事件(`TextDelta` / `ToolCallDelta` / `FinishEvent`)与 agent turn 事件(`TurnTextDelta` / `TurnToolStart` / `TurnToolEnd`)分两层
- `ToolRegistry.dispatch` 永不抛异常:错误都包成 `ToolResult(is_error=True)`,让模型自我修复
- `Conversation.validate` 在每次 send 前调用,把"远端 400"变成"本地立即报错"

---

## 项目结构

```
my-agent/
├── pyproject.toml
├── .env.example
├── src/my_agent/
│   ├── __main__.py            # python -m my_agent 入口
│   ├── config.py              # Config + load_config from .env
│   ├── cli/
│   │   ├── main.py            # app() — argv 或 REPL 分发
│   │   ├── repl.py            # Repl 类 + slash 命令
│   │   └── render.py          # ANSI 颜色 + truncate
│   ├── agent/
│   │   ├── loop.py            # AgentLoop.run_turn / run_turn_stream
│   │   ├── conversation.py    # Conversation + validate + save/load
│   │   ├── events.py          # TurnTextDelta / TurnToolStart / TurnToolEnd
│   │   └── errors.py          # AgentError 体系
│   ├── llm/
│   │   ├── client.py          # LLMClient 包 openai SDK + stream()
│   │   ├── types.py           # Message / ToolCall / Response / StreamEvent
│   │   └── stream.py          # assemble_stream(events) -> Response
│   └── tools/
│       ├── base.py            # Tool + ToolRegistry + ToolResult
│       ├── files.py           # read_file_tool, write_file_tool
│       └── shell.py           # run_bash_tool (timeout + cwd)
├── tests/
│   ├── unit/                  # 128 测试 < 5s
│   ├── integration/           # 默认 skip,pytest -m integration 启用
│   └── conftest.py
└── docs/
    ├── plans/                 # 设计文档 + 实施计划
    └── notes/                 # iter-N-retro.md 学习沉淀
```

---

## 演化路径

| 版本 | 主要能力 | 测试数 |
|---|---|---|
| **v0.0** | 一次性 chat,1 次 API call | 14 |
| **v0.1** | 单工具单回合(read_file) | 36 |
| **v0.2** | 多回合 ReAct loop + Conversation 不变量 | 59 |
| **v0.3** | 流式 + run_bash + ANSI 工具指示器 | 101 |
| **v0.4** | REPL + slash 命令 + /save /load | 128 |
| **v0.5** | 上下文压缩(sliding window + LLM summary)| 148 |
| v0.5.x(known limitation) | 单消息 / 最近 K 轮自己超预算时压缩失效(见 [iter-5-retro](docs/notes/iter-5-retro.md#-known-limitations)) | |
| v0.6(规划) | web_fetch / web_search | |
| v0.7(规划) | 跨会话长期记忆 | |
| v0.8(规划) | MCP 客户端 | |
| v0.9(规划) | sub-agent / Task 工具 | |
| v1.0(规划) | FastAPI + SSE web 包装 | |

---

## 开发

### 跑测试

```bash
pytest                          # 单测,< 5 秒
pytest -m integration           # 集成测试(真打 Qwen API)
```

### 添加新工具

1. 在 `src/my_agent/tools/<area>.py` 写 `_my_tool(args) -> str` 函数 + `my_tool = Tool(...)` 实例
2. 在 `src/my_agent/cli/main.py` 的 `build_registry()` 注册
3. 写测试 — 正常路径 + 异常路径

### 切换 provider

只改 `.env`:

```env
# Qwen via DashScope(默认)
DASHSCOPE_API_KEY=sk-...
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DEFAULT_MODEL=qwen-plus

# 或 DeepSeek
DASHSCOPE_API_KEY=sk-... (DeepSeek key)
DASHSCOPE_BASE_URL=https://api.deepseek.com/v1
DEFAULT_MODEL=deepseek-chat

# 或 GLM / Kimi / OpenAI 同理 — 只换三件事
```

---

## 文档

- **设计文档:** [`docs/plans/2026-05-15-my-agent-design.md`](docs/plans/2026-05-15-my-agent-design.md)
- **实施计划:** [`docs/plans/2026-05-15-my-agent-implementation-plan.md`](docs/plans/2026-05-15-my-agent-implementation-plan.md)
- **学习沉淀:** [`docs/notes/`](docs/notes/) — 每个 iter 一份 retro
