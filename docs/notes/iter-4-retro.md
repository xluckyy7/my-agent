# Iter 4 retro — REPL + slash 命令 + 跨 turn 持久化

**Tag:** `v0.4`
**Window:** 2026-05-19 ~ 2026-05-20
**核心交付:** `Repl` 类持有 conversation 跨多轮;`/help` `/quit` `/reset` `/save` `/load` 命令;ctrl-c 双击退出;`Conversation.save / load` JSON 序列化。**从"一次性 CLI"变成"会话伴侣"。**

---

## 做了什么

- `Message.from_api_dict` classmethod 镜像现有 `to_api_dict`(round-trip 覆盖所有 role)
- `Conversation.save(path)` 落 JSON,自动 mkdir parents
- `Conversation.load(path)` 用 `cls.__new__(cls)` 绕过 `__init__` 重建,拒绝 missing system / empty messages
- `Repl` 类:input() 主循环,持 loop+conv 两个状态,EOF 优雅退出
- 7 命令 + aliases(`/q` `/exit` `/?`)放进 `COMMANDS = {name: fn}` 字典分发
- 每条命令是 `(repl, arg) -> None` 函数,**不是 OOP** — 简单 5 倍
- `handle_input(line)` 公开方法,测试不必驱动 `input()`
- ctrl-c 双击退出(2 秒窗口),单击仅取消当前输入 — claude-code 风格
- cli/main.py 重构:argv 有 prompt 走 `repl.handle_input` one-shot,否则 `repl.run()` REPL 模式
- 128 测试

## 关键决策与原因

- **命令字典 + 裸函数,不要 OOP** — 7 个命令各 4-10 行,搞类是 over-engineer。加新命令 = 加一个函数 + 一行字典 entry。
- **`handle_input` 作为公开测试接口** — 把"读输入"和"处理输入"解耦。`run()` 是 thin wrapper 包 `input()`,真正逻辑在 `handle_input` 里。测试只测 `handle_input`,简洁 10 倍。
- **one-shot 也走 Repl** — 删了 `cli/main.py` 里那段重复 `_render_event`,统一渲染逻辑。
- **`Conversation.load` 用 `cls.__new__`** — `__init__` 会创建初始 system message,而 load 时 system 已在文件里。`__new__` 重建是 Python 工厂方法的标准做法,不算 hack。
- **不加 versioning** — 当前 v0.4 真要破坏性变更时再加;JSON 格式就是 OpenAI 标准 + `{"messages": [...]}` 包装,可直接喂回 API。
- **ctrl-c 双击退出**(2s 窗口)— shell 习惯是单击只清当前行,Python REPL 也是;但"应急退出"是 UX 必须的。**双击两全其美**:不破坏直觉,又给应急出口。这是 claude-code / ipython / psql 的共同选择。

## 学到的关键概念

- **REPL 是 agent "可用性" 的拐点** — 一次性 CLI 适合脚本,人类用户真要用 agent 一定是 REPL。
- **`__new__` vs `__init__`** — `__init__` 是"实例初始化",`__new__` 是"创造实例本身"。"已有完整状态从外部重建"用 `__new__` 比改 `__init__` 加 optional 参数干净。
- **Round-trip 测试是序列化代码的金标准** — `assert from_dict(to_dict(x)) == x`。简单但能覆盖几乎所有 bug。dataclass 自动生成 `__eq__`,不要钱。
- **测试设计:StringIO 替代真实流** — `Repl` 接受 `out=` `err=` 注入流。测试给 StringIO,prod 给 sys.stdout/stderr。"输出注入"模式让 UI 单元可测。
- **状态机式按键处理:用一个时间戳变量代替 FSM** — 双击退出靠 `_last_sigint` 时间戳就够,比正经状态机简单 5 倍,适用于"双击/长按/连击"类 UX。

## 踩的坑 / 让我意外的地方

- 初版 ctrl-c 只换行不退出,违反"应急退出"的直觉 — 用户在 prompt 上找不到出口。
- `handle_input("   ")` 没 strip 直接 truthy 判断,差点漏了一个边界 — 测试抓到。
- mock time.monotonic 时,要 `monkeypatch.setattr(repl_mod.time, "monotonic", ...)` 改模块内引用,而非全局 time。

## 我的补充(待你填)

- 这个 iter 哪里让我感觉特别重要?
- 哪里让我特别困惑?
- 我想再深挖什么?
