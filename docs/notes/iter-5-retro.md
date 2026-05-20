# Iter 5 retro — 上下文压缩

**Tag:** `v0.5`
**Window:** 2026-05-20 ~ 2026-05-20
**核心交付:** `ContextManager` 类 — sliding window + LLM summarization 两件套。conv 超 token 预算时自动压缩,模型仍记得早期对话的关键信息(目标、决策、文件路径)。

---

## 做了什么

- **依赖:** `tiktoken>=0.7`(token 估算,cl100k_base 编码器作 Qwen 的近似)
- **`count_tokens(text)` / `count_message_tokens(message)`** — 把消息 JSON 序列化后估 token + 4 token/message 协议开销
- **`ContextManager` 类:**
  - `budget`(默认 8000)+ `trigger_ratio`(0.8)→ 超过 6400 token 触发
  - `keep_recent_turns`(默认 4)→ 最近 4 个 user-turn 块保留原文
  - 切分点定在 user message 边界 → 永不切散 `assistant.tool_calls ↔ tool_result` 配对
  - 中间段交给同一个 client 做一次 LLM 调用,产 ≤200 字 summary(第三人称过去时)
  - 把中间段替换为单条 `[CONVERSATION SUMMARY]` 前缀的 user message
- **`AgentLoop`** 接受 optional `context_mgr`,每次 `send` 前调 `maybe_compact`
- **Config** 加 `context_budget` / `keep_recent_turns`,可通过 env vars `CONTEXT_BUDGET` / `KEEP_RECENT_TURNS` 覆盖
- **19 新测试**(8 token 估算 + 9 ContextManager + 2 AgentLoop 集成),累计 148

## 关键决策与原因

- **`user` role + `[CONVERSATION SUMMARY]` 前缀承载 summary** — 不污染 system,不假装 assistant,模型把它当 context 而非 instruction。Anthropic /compact 同款做法。
- **切分点必在 user message** — 保证永不切散 tool_call 与 tool_result 的配对。`validate()` 在 compact 后再调一次,双保险。
- **`tiktoken cl100k_base` 不是 Qwen 真 tokenizer** — Qwen tokenizer 要 HuggingFace transformers(几百 MB)。cl100k 估算偏差 10-20%,触发判断完全够,**不是计费场景没必要精确**。
- **summary 用同一个 LLM(qwen-plus)** — 没拆便宜 model。YAGNI,实际昂贵再换 qwen-turbo。
- **`lru_cache(maxsize=1)` 缓存 encoder** — 加载需数百毫秒到几秒,只算一次。
- **trigger_ratio = 0.8** — 预留 20% 给压缩本身的 prompt + summary 内容。
- **`keep_recent_turns = 4`** — 太少(1-2)模型容易感到上下文"突变";太多(10+)压缩频率不够。4 是社区主流值。

## 学到的关键概念

- **压缩是工业 agent 的"必须"** — 即使 1M token 上下文也会 lost in the middle。研究共识:short + dense > long + sparse。
- **协议不变量是压缩安全的基础** — Iter 2 投资的 `Conversation.validate()` 在 Iter 5 收获红利:压缩后再 validate 一次,任何"切坏 tool_call 配对"立刻 raise。**之前的投资在后期 iter 才显出价值,这是 agent 工程的常见现象**。
- **token 估算 ≠ 精确 token** — 估算是"触发判断",不是计费。15% 偏差完全可接受。追求精确就要拖 HF transformers 进来,得不偿失。
- **mock LLM 测压缩极容易** — 输入→输出是确定性的,`Response(content="fake summary")` 就能测全部行为。**9 个 ContextManager 测试一发就过**,是清晰契约 + 好测试设计的胜利。
- **2026 工业共识 = sliding window + LLM summary + 关键消息 pin**(三件套)。Microsoft Agent Framework 把这套形式化为命名模式 `Sliding window / Summarization / Tool-call collapse`,我们做了前两个,第三个留待后期。

## 🚨 Known Limitations(留给 future-self 的诚实清单)

当前实现**在两个真实场景下会失效**:

### A. 单条消息已超预算
用户粘贴大段代码;或 `run_bash` 跑 `cat 大文件` 返回几十 KB tool result。
- 实际表现:`maybe_compact` 因 `keep_recent_turns ≥ user_msg_count` 直接返回 False
- 后果:conv 仍超预算,下次 send 可能 API 400 / 模型截断 / finish_reason=length

### B. 最近 K 轮自己就超预算
最近 4 轮里有大 tool result,即使中间段被压缩,留下的"recent 4 turns"自己还是太胖。
- 实际表现:压缩"成功"但结果仍超预算
- 后果:同 A

### 现有测试没覆盖这两个 case
9 个 ContextManager 测试都基于"多轮小消息"常态。**这是一个真的洞,Iter 5 没补**。

### 工业方案(2026)
按优先级排:
1. **迭代压缩** — 压缩后仍超 → 递归减小 `keep_recent_turns` 重试
2. **Tool-result 截断** — tool message 超阈值 → 尾部截断 + `[N bytes truncated]` 标记
3. **单消息截断** — 任何 message 超阈值 → 截断 + 标记
4. **Tool-call collapse**(Microsoft 命名)— 老的 tool_call+result 对替换为引用占位符,真实内容存外部

最小补丁(覆盖 90% 场景)= 策略 1 + 2,约 50 行代码 + 3-4 测试。**留待用真任务撞到再补**。

## 我的补充(待你填)

- 这个 iter 哪里让我感觉特别重要?
- 哪里让我特别困惑?
- 我想再深挖什么?
- Known Limitation A/B 我什么时候真撞到过?
