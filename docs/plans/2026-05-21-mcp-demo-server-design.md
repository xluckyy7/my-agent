# MCP Demo Server — 设计文档

> 日期:2026-05-21
> 状态:已确认,待落地
> 上游:[`docs/multi-agent-learning-roadmap.md`](../multi-agent-learning-roadmap.md) 阶段 0 — "跑通一个 MCP server + client"
> 配套:v0.8 已实现 MCP **client**([`src/my_agent/mcp_layer/`](../../src/my_agent/mcp_layer/));本次实现 **server**,完成协议两端闭环

---

## 0. 目标

学习目标驱动:**站到 MCP 协议的 server 端**,把 v0.8 client 端踩过的协议概念(initialize / capabilities / tools-resources-prompts 三原语)从另一侧再过一遍。

**非目标:**
- 不做"项目内省 server"(暴露 my-agent 自身知识)
- 不做生产化(无监控、无日志框架、无重试)
- 不做远程 transport(stdio only,与 v0.8 client 一致)

---

## 1. 方案选型

| 维度 | 选择 | 替代方案 | 理由 |
|---|---|---|---|
| Server 定位 | 玩具 demo | 项目内省 / 通用工具 | 学习路径最短;真实数据会拉远焦点 |
| 实现方式 | 官方 mcp SDK(FastMCP) | 裸写 JSON-RPC / 双轨 | 与 v0.8 client SDK 选择对称;后续若想看协议细节,client 那边的 retro 已经覆盖 |
| 暴露原语 | tools + resources + prompts | tools-only / 二选一 | 一次走完三件套,看清各自设计意图 |
| 代码位置 | `examples/mcp_demo_server/` | `src/my_agent/mcp_demo/` / 独立 repo | examples/ 不污染主包定位(my-agent 是 client harness),git 同步又够近 |
| 每原语数量 | 各 2(无参 + 参数化) | 各 1(最小) | 工作量增量 ~30%,但能对照学习两种形态 |

---

## 2. 目录结构

```
my-agent/
└── examples/
    └── mcp_demo_server/
        ├── README.md              # 协议讲解 + 怎么跑 + 挂到 v0.8 client 的样板
        ├── server.py              # 主体,~150 行,大量"学习注释"
        ├── pyproject.toml         # 独立依赖(mcp[cli]>=1.0)
        └── tests/
            ├── __init__.py
            ├── test_tools.py      # FastMCP @tool 单测
            ├── test_resources.py  # @resource(含 URI template) 单测
            ├── test_prompts.py    # @prompt 单测
            └── test_e2e.py        # 子进程 + stdio_client + ClientSession 全协议
```

**关键决定:**
- 独立 `pyproject.toml` — server 自有依赖,主项目 `pyproject.toml` 不动
- `examples/` 不在主项目 `pytest` 扫描路径里 — 主测试集仍 < 5s
- README 必须给出 `~/.my-agent/mcp.json` 配置样板 — 闭环验证靠它

---

## 3. 三个原语的形态

### 3.1 Tools(2 个)

```python
@mcp.tool()
def add(a: int, b: int) -> int:
    """Return a + b."""

@mcp.tool()
def get_server_time() -> str:
    """Return current server-side ISO 8601 timestamp (UTC)."""
```

**学习点:**
- type hints 不是装饰 → FastMCP 用它们反射出 JSON Schema(协议契约的一部分)
- docstring 直接进 tool 的 `description` 字段(模型会读)
- 两个 tool 对照:有参 vs 无参,纯函数 vs 带副作用(`datetime.now`)

### 3.2 Resources(2 个)

```python
@mcp.resource("demo://docs/welcome")
def welcome_doc() -> str:
    """Static markdown welcoming the agent."""

@mcp.resource("demo://greeting/{name}")
def greeting(name: str) -> str:
    """Parameterized greeting; URI template binds {name}."""
```

**学习点:**
- 静态 URI vs RFC 6570 URI Template — 类比 REST `/users/{id}`
- Resource ≠ Tool 的核心:**resource 是"找数据用的"(读取),tool 是"做动作用的"(可能有副作用)**
- 对应协议方法:`resources/list` + `resources/read`

### 3.3 Prompts(2 个)

```python
@mcp.prompt()
def summarize_paragraph() -> str:
    """Return a single-string prompt asking for summary."""

@mcp.prompt()
def code_review(language: str, code: str) -> list[Message]:
    """Multi-message review prompt with code injected."""
```

**学习点:**
- 返回 `str` vs `list[Message]` 两种形态
- Prompt 是 **server → client 推荐"怎么问我"** 的能力(类比 GitHub MCP server 提供 "draft PR review" 模板,Claude Desktop UI 把它做成快捷入口)
- 对应协议方法:`prompts/list` + `prompts/get`

---

## 4. 协议数据流

```
client (v0.8 my-agent)            stdio              server (FastMCP)
─────────────────────             ─────              ──────────────────
spawn child process ────────────────────────────▶ start
                  ◀─── initialize request ─────
                  ─── initialize response ─────▶
                      (capabilities 协商: tools/resources/prompts ✓)

list_tools          ◀───── tools/list req ──────
                    ────── tools/list resp ─────▶
                          (返 JSON Schema)

call_tool("add",    ◀───── tools/call req ──────
  {a:1, b:2})       ────── tools/call resp ─────▶
                          (返 [{type:"text", text:"3"}])

list_resources / read_resource — 同理
list_prompts / get_prompt — 同理
```

**关键认知:**`initialize` 不是连接确认,而是**能力协商**。如果 server 不写任何 `@resource`,client 拿不到 `resources/*` 能力 — 这是 capability negotiation 的实际表现。

---

## 5. 测试策略

| 层 | 文件 | 跑什么 | 速度目标 |
|---|---|---|---|
| Unit | `test_tools.py` | import `add`/`get_server_time`,直接调函数 | < 0.1s |
| Unit | `test_resources.py` | 调 resource 函数,断 URI template 渲染 | < 0.1s |
| Unit | `test_prompts.py` | 调 prompt 函数,断 message list 结构 | < 0.1s |
| E2E | `test_e2e.py` | `stdio_client` + `ClientSession` 起子进程,跑完整 `initialize → list_X → call_X` | < 10s |

**E2E 测试的额外学习价值:** v0.8 client 踩过的 `AsyncExitStack`、event loop 关闭等坑,在这里从 server 启动方再撞一遍,正好对照。

---

## 6. 与 v0.8 client 的闭环

`README.md` 必含:

```jsonc
// ~/.my-agent/mcp.json 样板片段
{
  "servers": {
    "demo": {
      "command": "python",
      "args": ["/abs/path/to/my-agent/examples/mcp_demo_server/server.py"]
    }
  }
}
```

**验收标准:** `python -m my_agent`,问 "用 demo 的 add 工具算 3+5",REPL 工具指示器看到 `▸ demo__add {a:3,b:5}` → `✓ ... 8`。

---

## 7. 错误处理(故意做最少)

- Tool 函数抛异常 → FastMCP 自动 `tools/call` 错误响应(`isError: true`)→ v0.8 client `ToolResult(is_error=True)` 接得住
- Resource URI 不存在 → SDK 返 `resources/read` error
- **不写额外兜底** — 学习阶段先看 SDK 默认行为,清楚后再决定要不要加层

---

## 8. 风险与已知限制

| 风险 | 评估 | 处理 |
|---|---|---|
| FastMCP API 与 retro 中描述的概念不严格对齐 | 中 | 实现时用 context7 拉最新 mcp SDK 文档对照 |
| `examples/` 独立 pyproject 依赖 mcp 与主项目重复安装 | 低 | 接受;独立性更重要 |
| E2E 测试需要打开子进程,CI 环境可能不稳定 | 中 | 标记 `@pytest.mark.slow`,本地必须跑过,CI 可选 |
| URI template 的细节(空格、特殊字符)与 RFC 6570 完整规范的差距 | 低 | 玩具 demo 不深挖,只用 `{name}` 这一种形态 |

---

## 9. 验收清单

- [ ] `examples/mcp_demo_server/server.py` 跑得起来(`python server.py` 不报错并阻塞等输入)
- [ ] 4 份测试文件全过(unit + e2e)
- [ ] README 给出可复制的 `~/.my-agent/mcp.json` 片段
- [ ] 真实跑通:my-agent REPL 调到 `demo__add` 并拿到正确结果
- [ ] 三个原语在 v0.8 client 中至少各被调到一次(tools 已支持,resources/prompts 是 client 待补)
  - 注:client 端 list/call resources/prompts 的能力 v0.8 没实现,验收时只要协议层通过 `mcp inspector` 或 e2e 测试即可,不要求 my-agent 这一侧补客户端

---

## 10. 后续(本次不做)

- v0.8.x:my-agent client 端补 resources / prompts 调用支持(让模型可以读 server resource、用 server prompt)
- 把 demo server 重写一份"裸 JSON-RPC"版本对照,深入协议 framing
- 把 demo 升级成"项目内省 server"(暴露 iter retro 作为 resource、search-code 作为 tool)
