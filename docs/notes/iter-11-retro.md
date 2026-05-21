# Iter 11 retro — Hook 系统 + Langfuse 插件

**Tag:** `v1.1`
**Window:** 2026-05-21 ~ 2026-05-21
**核心交付:** Claude Code 风格 hook 系统 + 第一个 Python 插件(langfuse)。
agent 现在可以被外部"旁观",所有关键事件(模型调用、工具调用、turn 边界)
能挂监听器,不动核心代码。

---

## 做了什么

- `src/my_agent/agent/hooks.py`:
  - `HOOK_EVENTS` 7 个事件:`SessionStart` / `UserPromptSubmit` /
    `PreModelCall` / `PostModelCall` / `PreToolUse` / `PostToolUse` / `Stop`
  - `HookSpec` dataclass:`type` (command|python) + matcher 正则 +
    (command: command/timeout) / (python: module/function)
  - `HookEvent` payload:`{event, timestamp, data}`
  - `load_hooks(home)` 读 `~/.my-agent/hooks.json`(schema 同 Claude Code)
  - `HookManager.fire(event, data, subject=...)`:**永不抛异常**(失败 stderr 不 raise),
    python 模块缓存,matcher 正则过滤
- **wire 进 5 个地方:**
  - `ToolRegistry` 接 `hooks` 参数 → 每次 dispatch 前后触发 `Pre/PostToolUse`
  - `LLMClient` 接 `hooks` 参数 → send/stream 前后触发 `Pre/PostModelCall`
  - `AgentLoop` 接 `hooks` 参数 → `UserPromptSubmit` 在入口、`Stop` 在退出
  - `cli/main.py` 启动构造 HookManager,触发 `SessionStart`
  - `web/server.py` 同上
- **`src/my_agent/plugins/langfuse_plugin.py`**:8 个 hook 入口函数,
  模块级 session 状态字典(per session_id 维护 span stack),
  懒加载 Langfuse client(没 key 时优雅 noop)
- 新增 **28 测试**(16 hooks + 3 integration + 9 langfuse),累计 278

## 关键决策与原因

- **复用 Claude Code 的 schema** — `~/.my-agent/hooks.json` 顶层 `hooks` 对象,key 是
  event 名,值是 hook spec 列表。用户读过 Claude Code 文档,迁移零摩擦。
- **两种 hook 类型并存** — `command`(shell,stdin 拿 JSON)适合"我有个现成脚本想跑";
  `python`(module:function)适合 langfuse 这种**有状态、跨事件维护引用**的插件。
  shell 跑完 cleanup 拿不到状态,python 模块全局 dict 天然能存。
- **hook 失败永不 raise** — 一个坏插件不该让 agent 起不来或挂掉。所有异常 catch +
  stderr 报告。同时也意味着**hooks 不能"阻塞"工具执行**(故意的:Claude Code 的
  block 语义复杂,v1.1 还不上)。
- **python 模块缓存** — `importlib.import_module` 只调一次,后续 lookup O(1)。
  langfuse client 也是模块级 lazy init,跨 turn 共享同一个 client(避免重复 OTel setup)。
- **matcher 是 regex 而非 glob** — Python `re.search` 一行,比 fnmatch 更灵活(`run_bash|web_fetch`
  这种 alternation 直接写)。
- **subject 是 caller 显式传的字符串,不是 event.data 的整体序列化** — 让 matcher
  精准(只匹配 tool_name,不被无关数据干扰)。
- **payload 用 `data: dict` 而非命名字段** — 7 个事件各有各的字段,统一接口让 fire
  的 caller 自由,plugin 自己解 `data["tool_name"]` 等。代价是没有类型 narrowing,
  但 v1.1 接受这个 trade-off。
- **`SessionStart` 在 CLI 和 web 启动时触发一次** — 等价于"agent 开机",不是
  "每次对话"。每次对话用 `UserPromptSubmit`。
- **`Stop` 触发不区分正常完成 vs 预算超** — `data["reason"]` 标注;langfuse 会
  把 budget_exceeded 标记成异常 span。
- **`langfuse_plugin` 在没 key 时优雅 noop** — `_ensure_client` 返 None,所有 hook
  入口提前 return。**这是插件的"良民习惯"**:不要因为配错就阻塞 agent。
- **per-session span stack** — langfuse 的 generation/span 是嵌套的(turn → llm_call,
  turn → tool → ...)。我们维护 `{session_id: [span1, span2, ...]}` 字典,
  Pre 事件 push、Post 事件 pop。**简单可靠,适合 single-thread 同步 hook**。

## 学到的关键概念

1. **Hook 框架 = "事件源 + 调度器 + 适配器"** — 我们在 5 个地方插了事件源
   (loop / tool registry / client / cli / web),HookManager 是调度器,
   plugin 是适配器(把 my-agent 事件翻译成 langfuse / file / 其他系统)。
   **新增观察方式时只加 plugin,不动核心**。
2. **"matcher 在 hook spec 内"是 Claude Code 的妙笔** — 而不是在每个 plugin
   自己内部判断 if tool_name == "x"。matcher 是**配置时**决定关心什么,
   而不是**运行时**;减少了插件代码的重复 if 检查。
3. **`importlib.import_module + getattr` 是 Python 动态调度的瑞士军刀** — 不需要
   entry_points,不需要 setuptools 入口,直接字符串 → callable。**只要 plugin
   能被 import,就能被 hook 系统调用**。
4. **`_reset_for_tests()` 函数是模块级状态的标准化测试种子** — 不要试图 reset
   全局变量直接(测试间互相污染),而是导出一个明确的 reset 函数,autouse
   fixture 调用。
5. **Hook **必须**永不抛异常** — agent 是主线,plugin 是副线。副线坏了主线继续。
   这跟 Iter 1 学的"`ToolRegistry.dispatch` 永不抛"是同一原则:**让外围系统的
   错误成为可观察事件,而不是 propagate 的异常**。
6. **OTel-based SDK(langfuse 4.x)的非 context-manager 用法** — 调
   `start_observation()` 拿对象,后续 `.end()`。但 OTel context 不会随着这种
   分离调用自动维护父子关系 — 如果你要严格嵌套,就用 context manager。我们这里
   每个事件单独 push/pop,父子关系不依赖 OTel ContextVar。

## 踩的坑 / 让我意外的地方

- langfuse 4.x 把 API 从 v2 的 `client.trace().generation().end()` 改成 OTel 风格的
  `client.start_observation(as_type="generation")`。文档相对少。我用 `dir()`
  反查 API。
- 第一次写 wire 时忘了在 stream 路径的 finish chunk 后触发 `PostModelCall`,
  导致 langfuse 的 generation 永远不关。补上后才对。
- 测试 langfuse 插件时,`_reset_for_tests` 没 clear `_sessions` 导致状态串台 —
  加 `_sessions.clear()` 修复。

## 🚨 Known Limitations

1. **hooks 不能 block / mutate** — Claude Code 的 hook 可以通过返回码或 stdout JSON
   阻止工具执行。我们 v1.1 只观察,不干预。**未来 v1.1.x 可加 stdout JSON
   解析 `{"block": true, "message": "..."}`**。
2. **hooks 同步执行** — 慢插件拖慢主流程。langfuse 客户端内部异步批处理,所以
   实际感知延迟很小,但若 plugin 做同步 HTTP 调用会阻塞。
3. **session_id 提取靠 caller 显式塞 data** — CLI 不知道"session_id"概念,所以
   传 "default"。web/SSE 那条路会传真 id(还需 web/app.py 主动塞,当前没塞)。
4. **没有 hook 顺序保证** — 同一事件多 hook 时按 config 顺序触发,但若一个 hook
   慢、另一个不依赖它,不能并行(同步执行)。
5. **langfuse 插件的状态字典是 process-global** — uvicorn 多 worker 模式下每个
   worker 自己一份,trace 可能被切碎。**v1.1.x 可以借 langfuse 的 trace_id 桥接**。

## 我的补充(待你填)

- 这个 iter 哪里让我感觉特别重要?
- 哪里让我特别困惑?
- 我想再深挖什么?
- 我配过 langfuse 真账户跑过吗?dashboard 显示了什么?
- 写过自己的第二个插件没?(slack 通知 / cost tracker / activity logger 等)
