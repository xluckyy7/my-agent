# Iter 3 retro — 流式输出 + run_bash + 工具指示器

**Tag:** `v0.3`
**Window:** 2026-05-18 ~ 2026-05-18
**核心交付:** `LLMClient.stream()` 流式解析;`AgentLoop.run_turn_stream` yield 类型化 turn events;CLI 加 ANSI 颜色和工具调用指示器;新增 `run_bash` 工具(timeout + cwd + stdout/stderr 捕获)。

---

## 做了什么

- `StreamEvent` 三类:`TextDelta` / `ToolCallDelta` / `FinishEvent`
- `LLMClient.stream()` 解析 chunk 增量(text + tool_calls.index 分桶累积 + 跳过 heartbeat)
- `assemble_stream(events)` 把事件流折回 `Response`,与非流式 send() 返回形态一致
- `AgentLoop.run_turn_stream` 用 "tee" 模式:边消费流边 yield 给 UI + 收集事件交 assemble
- `TurnTextDelta` / `TurnToolStart` / `TurnToolEnd`(带 duration_seconds、is_error)
- `cli/render.py` ANSI 颜色 + truncate + TTY 感知 color()
- CLI 用 `match-case` 渲染:`▸ tool {args}`(cyan) → `✓ Ns {preview}`(green) / `✗ ... error`(red)
- `run_bash_tool`:`subprocess.run(shell=True, cwd=Path.cwd(), capture_output=True, timeout=int)`
- **Qwen 空 id bug 修复**(诊断+修+加固),加 chunk 级 debug + 第 5 条不变量(`tool_call.id` 非空)
- 101 测试

## 关键决策与原因

- **`stream()` 是低级原语,不做累积** — yield 原子事件,把"累积成 Response"的责任丢给上游,各层独立测试。
- **`run_turn_stream` 改 yield TurnEvent(不只字符串)** — 给 CLI 提供更多元数据。配合 `match-case` 极度优雅,加新 event 类型时编译器/类型检查器能提示遗漏分支。
- **`time.monotonic()` 测耗时** — 不是 `time.time()`。永远不受系统时间调整影响。
- **不引 rich** — 80 行 ANSI 够用,rich 留到 Iter 4 REPL 一起做。少一个依赖,Iter 4 重构时少一个迁移负担。
- **TTY 感知的 color()** — 非 TTY(管道、重定向)自动 fallback 纯文本,避免 `> out.txt` 满文件逃逸字符。
- **没做 sandbox** — 学习项目里 YAGNI;路径白名单 / chroot 远超 v0 范围。用户对运行的命令负责。

## 学到的关键概念

- **流式协议下"何时知道 finish_reason"** — 必须等到流末尾。不能在中间决定要不要分发工具。
- **`tool_calls[i].index` 是 parallel tool calls 拼回的关键** — 没它流式根本拼不对。
- **Qwen 流式 quirk:第一个 chunk 给真 id,后续 chunk 把 id 设成 `""`(不是 null)** — 我们的 `if ev.id is not None` 会被"覆盖"成空串。修法:在 `stream()` 出口 `raw_id or None` 归一。
- **"宽松的 provider 是潜在炸弹"** — Qwen 没 reject 空 id 看似一切正常,换 OpenAI 立即翻车。本地不变量校验是保护未来的自己。
- **事件分层是 streaming agent 系统的关键模式** — 两层流(LLM chunk → harness 累积 → turn event → UI 渲染),各层独立测试。Iter 9 sub-agent 时还要再加一层。
- **`yield` 让函数变 generator,`return` 触发 StopIteration** — 用 return 不带值表示流结束,caller 的 `for x in ...` 自然终止。

## 踩的坑 / 让我意外的地方

- mock 引用陷阱:`call_args.kwargs` 抓的是**引用**,后续 mutation 会改它。**用 side_effect 在调用瞬间抓快照**。
- 写 chunk 级 debug 时 MagicMock.model_dump() 返 MagicMock,json.dumps 炸。加 isinstance(..., dict) 兜底。
- `MY_AGENT_DEBUG=1` 从 shell 泄漏到 pytest 让 6 个测试莫名失败;`conftest.py` 加 autouse `monkeypatch.delenv` 隔离。

## 我的补充(待你填)

- 这个 iter 哪里让我感觉特别重要?
- 哪里让我特别困惑?
- 我想再深挖什么?
