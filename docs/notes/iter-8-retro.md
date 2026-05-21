# Iter 8 retro — MCP 客户端

**Tag:** `v0.8`
**Window:** 2026-05-21 ~ 2026-05-21
**核心交付:** my-agent 接入 MCP(Model Context Protocol)生态。配 `~/.my-agent/mcp.json` 后启动时自动 spawn server、列工具、namespaced 注册到 ToolRegistry,模型像调内置工具一样调远端工具。

---

## 做了什么

- 新依赖:`mcp>=1.0`(官方 Python SDK)
- 新模块 `src/my_agent/mcp_layer/`(故意不叫 `mcp` 避开 SDK 命名冲突):
  - `config.py`:`~/.my-agent/mcp.json` loader,schema 同 Claude Desktop `({servers: {<name>: {command, args, env}}})`
  - `client.py`:sync wrapper(`fetch_tools_sync` / `call_tool_sync`)用 `asyncio.run` + `AsyncExitStack`
    - 每次调用 respawn server(简单但慢,~13s 每次)
    - `_open_session` / `_close_session` 是测试 mock 点
  - `adapter.py`:`mcp_tool_to_internal` 把 MCP tool → 内部 `Tool`,命名 `<server>__<tool>` 防冲突
    - `build_mcp_tools(spec)` 错误时返空 list 不挂主流程
- `cli/main.py` `build_registry` 加载 mcp_specs → `build_mcp_tools` 注册
- `cli/repl.py` 加 `/mcp` 命令(列出 namespace 工具,按 server 分组)
- 23 新测试(9 config + 6 client + 7 adapter + 1 registry)+ 3 /mcp 测试,累计 226 unit

## 关键决策与原因

- **用官方 `mcp` SDK 而非裸写 JSON-RPC** — 一致于已有"用 openai SDK / httpx / trafilatura 不重写"。学习放在**集成层**(怎么把 async SDK 套进 sync harness),不在协议 framing。
- **包名 `mcp_layer`** — 避开与 `import mcp` 的导入歧义。源码读 `from my_agent.mcp_layer.x` vs `from mcp import y` 一目了然。
- **`asyncio.run + AsyncExitStack` 包双层 async-with** — `stdio_client` 和 `ClientSession` 都是 async context manager,必须用 `AsyncExitStack` 才能 cleanly 串联。这段是值得收藏的 snippet。
- **每次 tool call 都 respawn server** — v0.8 故意简单,验证端到端正确性。代价是 13 秒级延迟。**v0.8.x 优化**:背景线程跑 asyncio loop + 持久 ClientSession,大概 10x 提速。
- **MCP tool 命名空间 `<server>__<tool>`** — 直接抄 Claude Code 命名风格。**好处:**(a) 不冲突;(b) 模型看 tool 名一眼知道是远端;(c) `/mcp` 命令简单按 `__` 分组。
- **`build_mcp_tools` 失败时返空 list** — 一个坏 MCP server 不该让 agent 起不来。打到 stderr 让用户看到,继续用内置工具。
- **tool fn 闭包用默认参数 `_server=server, _name=mcp_tool.name`** — 经典 Python 默认参数 trick 锁死值,防止后期循环里改造时被晚绑定坑。

## 学到的关键概念

- **集成异步 SDK 到同步 harness 的标准模式** — 不是"全改成 async"也不是"侵入 SDK",而是 **`asyncio.run + AsyncExitStack` 在边界包一层**。适用于任何"我的代码 sync,某依赖 async"的场景。
- **MCP 协议本质 = "JSON-RPC 2.0 + initialize handshake + tool/resource/prompt 三类原语 + 双向通信"** — 通过 SDK 看实际调用,能反推协议关键概念:
  - `initialize` — 协议版本协商 + capabilities 协商 + 双方自我介绍
  - `tools/{list,call}` — 函数调用风格(类 OpenAI function calling)
  - `resources/{list,read,subscribe}` — 只读数据,URI 标识(file:// / github:// / 自定义)
  - `prompts/{list,get}` — 服务端预制提示词模板
  - `sampling/createMessage` — server 反向请求 client 跑 LLM(很妙的设计)
  - 用 SDK 不等于黑盒,反而能聚焦"协议在做什么",而不是"框架在帮我做什么"
- **JSON-RPC 是 transport-agnostic 的** — 协议归协议,传输归传输。MCP 选 stdio 只是因为子进程 server 最自然。同样 JSON-RPC 消息可以走 HTTP / WebSocket / TCP。
- **MCP server 启动慢(几秒到十几秒)** — Python venv + 包管理 (uv/npm) 都不快。这就是为什么持久连接是必需优化。
- **adapter 模式让外来 tool 与内置 tool 完全平等** — 通过 `Tool` 这一抽象,模型层面看不出来 `read_file` 和 `filesystem__read_file` 来自哪。**统一接口的胜利,Iter 1 那个`Tool` 数据类的投资在 Iter 8 才显出全部价值**。
- **闭包默认参数 trick** — `lambda x, _bound=value: ...` 是 Python 闭包标准防陷阱写法。在循环里建闭包尤其重要。

## 踩的坑 / 让我意外的地方

- mcp SDK 的 `stdio_client` 和 `ClientSession` 都是 async context manager,**两者都需要 enter,且必须按顺序 exit**。第一次写时把 read/write 拿出 with 块外,出了"event loop closed" 错误。AsyncExitStack 解决。
- 测试 mock 时 mock_session 需要 `_my_agent_stack` 属性才能让 `_close_session` 不报错。设计的"把 stack 挂到 session 上"虽然有点 hack,但测试也好 mock。
- 真打 demo 第一次跑了 13.28 秒,本以为坏了。实际是 uvx 第一次拉 `mcp-server-fetch` 包(45 个依赖)。第二次跑会快(包已缓存)。

## 🚨 Known Limitations

按优先级排:
1. **每次调用 respawn server**(~3-13s 延迟)— v0.8.x 应做:背景线程跑持久 asyncio loop,共享 ClientSession 跨 tool calls
2. **只支持 stdio transport** — 没有 HTTP / Streamable HTTP,接不了远程 server
3. **只读 tools** — resources / prompts 没接,损失一些 server 提供的能力
4. **没有 tool-discovery 缓存** — 每次启动都 spawn → list_tools → cleanup,启动慢
5. **没有 session-scoped state** — server 是无状态调用,有些 server (DB session, transactions) 需要持久 session

## 我的补充(待你填)

- 这个 iter 哪里让我感觉特别重要?
- 哪里让我特别困惑?
- 我想再深挖什么?
- 我接过哪些 MCP server?哪些好用,哪些慢得受不了?
- 那个 13s 延迟我真撞到 bottleneck 了吗?
- 我想去看看哪个开源 MCP server 的源码(filesystem? git? sentry?)?
