# Iter 2 retro — 多回合 agent loop

**Tag:** `v0.2`
**Window:** 2026-05-17 ~ 2026-05-17
**核心交付:** `run_once` 升级为 while 循环;`Conversation` 类承载历史并自检 4 条协议不变量;`AgentLoop` 类把循环抽离。**第一次拥有真正通用的 ReAct agent**。

---

## 做了什么

- `Conversation` 类:`append_user` / `append_assistant` / `append_tool_result` / `to_api_format` / `validate`
- 4 条不变量校验(写在 `validate()` 里):
  1. system 恰好一条且在 index 0
  2. assistant.content 与 tool_calls 不能同时空
  3. assistant.tool_calls 后必须紧跟同等数量 tool 消息,id 顺序对齐
  4. tool 消息不可成孤儿
- `AgentLoop.run_turn` while 循环直到 `finish_reason != "tool_calls"` 或 `max_iterations`
- 自定义异常 `AgentError` / `AgentBudgetExceeded` / `ConversationInvalid`
- `write_file_tool`(配合 read_file 形成典型双工具场景)
- 59 测试

## 关键决策与原因

- **`Conversation.validate()` 在每次 send 前调用** — 把"远端 400 错误"变成"本地立即报错"。调试效率天差地别。
- **`max_iterations` 默认 20** — 真实任务普遍 5-8 轮收敛,20 是"够用 + 出错不至于烧太多钱"的折中。
- **`AgentLoop` 持有 tools(静态),`run_turn` 接外部 conversation(可换)** — 这种不对称是有意的:tools 在 agent 生命周期内不变,conversation 跨 turn 演进必须由 caller 控制。为 Iter 4 REPL 和 Iter 9 sub-agent 铺路。
- **`finish_reason == "length"` 直接返回不重启 loop** — 避免无限拆分回复。后期想"自动续写"再加策略。

## 学到的关键概念

- **ReAct 论文里的 thought-action-observation 在 OpenAI 协议下:**
  - thought:隐含在 assistant 生成 token 流的内部(没显式字段)
  - action:`tool_calls`
  - observation:`role: "tool"` message
- **不变量 = 协议的"形式化合同"** — 4 条不变量每条对应一种 API 会拒绝的 400 形态。写成代码而不只在脑子里。
- **kwargs vs args 在测试 mock 里有差异** — `call_args.args[0]` vs `call_args.kwargs["messages"]`。生产代码用 kwargs 可读性好,测试得跟着改。

## 踩的坑 / 让我意外的地方

- 实测 "读 README 再写一份简介" 任务 3 次 send 完成,完美对照 ReAct 序列。
- demo 时 agent 真的把 README.md 修改了 — 还原前一刻反应过来"它是 agent,不是建议",这就是 agent 的"动手"特质。

## 我的补充(待你填)

- 这个 iter 哪里让我感觉特别重要?
- 哪里让我特别困惑?
- 我想再深挖什么?
