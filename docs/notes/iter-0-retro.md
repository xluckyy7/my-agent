# Iter 0 retro — 最小 chat loop

**Tag:** `v0.0`
**Window:** 2026-05-17 ~ 2026-05-17
**核心交付:** 一行 `python -m my_agent "..."` 跑一次 API 调用,打印回复。

---

## 做了什么

- `pyproject.toml` + venv,锁定 Python 3.10+
- `Config` 从 `.env` 读 DASHSCOPE_API_KEY / base_url / model / max_tokens
- 内部消息模型 `Message` / `ToolCall` / `Response`,采用 **OpenAI 原生格式**(不做翻译层)
- `LLMClient` 包 `openai` SDK,默认走 DashScope 兼容端点跑 Qwen
- `MY_AGENT_DEBUG=1` 环境变量 dump REQUEST / RESPONSE JSON 到 stderr
- 14 单测 + 1 集成测试

## 关键决策与原因

- **裸写 + OpenAI 原生协议(不引 LangChain / Agent SDK)** — 学习目标决定的:工具链越薄,概念越能落到自己脑子里。
- **`.env` 用 `find_dotenv(usecwd=True)`** — `dotenv` 默认按 source __file__ 向上找 `.env`,这会让 `chdir` 隔离失效;改 cwd-based 后行为更直观,测试也好写。
- **`Response.raw` 保留原始响应** — 后期 debug / 录制重放都靠它,几行预留换无限灵活。

## 学到的关键概念

- **API 协议是给程序员看的;模型实际看到的是 chat template 渲染后的 token 流。**JSON 只是包装,通过 Jinja2 模板被服务器拼成 `<|im_start|>system\n...\n<|im_end|>\n<|im_start|>user\n...` 这样的纯文本。模型生成的也只是 token,服务器再解析回 OpenAI JSON。
- **OpenAI 兼容模式是协议适配,不是模型适配** — 同一份 `openai.OpenAI(base_url=...)` 客户端代码能跑 Qwen / DeepSeek / GLM / Kimi / GPT,只换 base_url + model + key。
- **`finish_reason` 的可能值** — `stop` / `length` / `tool_calls` / `content_filter`,每个对应不同的后续动作。

## 踩的坑 / 让我意外的地方

- `python-dotenv` 默认搜索路径基于 caller `__file__`,而非 cwd。修了之后测试隔离干净。
- macOS Python 3.10.13 from pyenv;Python 3.11+ 的特性(如 `tomllib`)v0 一概没用,降级 requires-python = 3.10 完全够。
- openai SDK 2.x 跟 1.x 的 `client.chat.completions.create()` 兼容,装更新版没问题。

## 我的补充(待你填)

- 这个 iter 哪里让我感觉特别重要?
- 哪里让我特别困惑?
- 我想再深挖什么?
