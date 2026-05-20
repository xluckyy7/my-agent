# Iter 1 retro — 单工具单回合

**Tag:** `v0.1`
**Window:** 2026-05-17 ~ 2026-05-17
**核心交付:** agent 能调用 `read_file` 工具:模型决策 → harness 分发 → 结果回灌 → 模型基于结果生成最终回话。**一次完整 ReAct 闭环(单回合)**。

---

## 做了什么

- `Tool` dataclass(name + description + JSON Schema parameters + fn)
- `ToolRegistry` — 名称→Tool 映射 + `dispatch()` **永不抛异常**(异常→ `ToolResult(is_error=True)`)
- `read_file_tool` — 第一个真工具(用 `Path.read_text(encoding="utf-8")`)
- `cli.main.run_once` — 实现"最多一回合 tool use"契约:send → tool_calls → dispatch → send → 返回 final text
- 36 测试

## 关键决策与原因

- **`dispatch()` 不抛异常** — 这是 agent loop 简洁的关键。任何错误(unknown tool / 非法 JSON / fn 内部异常)都包成 `ToolResult(is_error=True)`,让模型把错误当 observation 自我修复。loop 不必 try/except。
- **`Tool.fn` 强类型签名 `Callable[[dict], str]`** — 输入 dict、输出 str。后期 async / 结构化返回需要再放宽。
- **`get_schemas()` 直接产 OpenAI 嵌套格式** — 不做中间抽象层,YAGNI。
- **`description` 写详细,带 "Use this when..."** — schema 是 chat template 拼进 system prompt 的一部分,**写得越好模型调用越准**。这就是 schema engineering。

## 学到的关键概念

- **`arguments` 是 JSON 字符串,不是 dict** — OpenAI 协议规定。dispatch 必须自己 `json.loads`,还要兜住模型偶尔吐非法 JSON 的情况。
- **JSON Schema 进 prompt** — `parameters.properties.path.description` 不是程序员注释,是给模型读的。注册 5 个工具 prompt_tokens 暴涨 500-1000。
- **错误也是 observation(ReAct 闭环的关键)** — 把"读文件失败"当成普通输入塞回模型,它会自己决定下一步(重试 / 换路径 / 放弃)。
- **assistant.tool_calls 必须跟同等数量的 tool message 配对,tool_call_id 一致** — 协议硬规定,违反 400。

## 踩的坑 / 让我意外的地方

- 模型(Qwen)在 tool_calls 响应里 content 是 `""` 而不是 `null`,我们内部归一成 None。这种 provider 之间的小差异以后会反复出现。
- **prompt_tokens 22 → 212** 一上工具立刻翻 10 倍 — schema 体积影响实际成本。
- 真实 demo 时模型用了 `path: "README.md"`(没加 `./` 前缀),它"理解"了相对路径概念,跑通。

## 我的补充(待你填)

- 这个 iter 哪里让我感觉特别重要?
- 哪里让我特别困惑?
- 我想再深挖什么?
