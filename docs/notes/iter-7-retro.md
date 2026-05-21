# Iter 7 retro — 跨会话记忆

**Tag:** `v0.7`
**Window:** 2026-05-21 ~ 2026-05-21
**核心交付:** 真正的跨会话长期记忆 — 项目级 `./AGENT.md` + 用户级 `~/.my-agent/memory/MEMORY.md` 启动时注入 system prompt;`remember` 工具让 LLM 主动写;`/memory` REPL 命令查 / 清。

---

## 做了什么

- `src/my_agent/agent/memory.py`:
  - `load_project_memory(cwd)` — 读 `./AGENT.md`(空文件视作 None)
  - `load_user_memory(home)` — 读 `~/.my-agent/memory/MEMORY.md`
  - `compose_system_prompt(base, project, user)` — 拼出最终 system,顺序 base → project → user
- `src/my_agent/tools/memory_tool.py`:
  - `make_remember_tool(home)` 工厂模式产 Tool 实例(home 可注入便于测试)
  - LLM 调 `remember({content})` → 追加 `- YYYY-MM-DD: <content>\n` 到 MEMORY.md
  - description 明确"只存值得跨会话的,不存临时任务状态"
- `cli/repl.py` 加 `/memory` 命令 — `list` 显示当前;`clear` 清空文件
- `cli/main.py` 启动时:
  - 用 `compose_system_prompt` 注入两份记忆
  - 注册 remember 工具(绑 HOME)
- 25 新测试(12 memory + 8 remember + 5 /memory),累计 200 unit

## 关键决策与原因

- **两层记忆**:project + user,而不是 3+ 层(per-memory file + index)。**第一版极简,YAGNI**;复杂结构推 v0.8+。
- **简单 markdown,无 YAML frontmatter** — 计划里设计的 frontmatter(type/category/links)推后。当前每条记忆 = 一行 `- YYYY-MM-DD: content`。
- **`make_remember_tool(home=...)` 工厂模式** — 不用模块级常量,因为 home 路径在测试时必须可注入。这是**依赖注入在工具层**的实践。
- **`compose_system_prompt` 顺序固定**:base → project → user。base 是"我是什么",project 是"这个项目的规矩",user 是"长期事实"。**顺序影响模型权重**:project 比 user 更近 stop token,更易被遵循;user 在尾部容易被新对话稀释。
- **启动时一次性加载,不懒加载** — 启动后改 MEMORY.md 当前会话不会自动重读。如果用户想"现场刷新",`/reset` 后会重建 conversation(但 system 还是启动时的)。**真要现场刷新加 `/memory reload` 命令即可**(后期补)。
- **`remember` description 明确"don't use for ephemeral state"** — 避免模型把"我刚才说要读 README"这种短期内容也存进去。学自 Claude Code memory 系统的"What NOT to save"。

## 学到的关键概念

- **跨进程 memory = 文件 + 启动时加载** — 不需要任何花活(数据库 / 服务 / 锁)。Unix 哲学:**plain text + filesystem + 每次进程重读**。这套对 v0 完全够用,且可读、可手编、可 git diff。
- **`remember` 的 description 是"用法手册"** — 模型读它决定何时调用。description 写得不好,要么模型乱存噪音,要么从来不调用。**这是 schema engineering 在记忆系统的具体体现**。
- **system prompt 注入 vs 工具自检** — 我们选了"启动注入 system",另一种是"提供 `recall(query)` 工具让模型按需检索"。前者简单粗暴(一次性加载所有),后者优雅但需要向量库 / 全文检索。**v0.7 走"全加载",当 MEMORY.md 长到几 KB 才考虑切换**。这是工业界 2026 大多数 agent 在小规模下的选择。
- **"启动时副作用"很容易难测** — 我们把 main.app() 里的副作用拆成 `load_project_memory` / `load_user_memory` / `compose_system_prompt` 三个纯函数,这三个极易单测。**纯函数核 + 外壳粘合**模式的胜利。
- **`HOME` env var 是 Unix 长期记忆的标准锚点** — 比 hardcode `Path.home()` 灵活:测试可以 `monkeypatch.setenv("HOME", str(tmp_path))`,prod 用真 HOME。**遵守 Unix 约定即测试友好**。
- **`__new__` vs `__init__`** — `Conversation.load` 用 `cls.__new__(cls)` 重建,因为 `__init__` 会创建初始 system message,而 load 时 system 已在文件里。Python "工厂方法重建实例"的标准做法,不算 hack。

## 踩的坑 / 让我意外的地方

- 实测两个会话(一个调 remember 写 vim 偏好,另一个新进程问"我用什么编辑器"),agent 真的零历史答对了。这种"agent 真的记得"的体验跟之前每次 reset 完全失忆很不一样。
- 写测试时差点忘了 mock `Path.home()`,差点把测试污染到真实 `~/.my-agent/`。`HOME` env var 注入解决。

## 🚨 Known Limitations(诚实清单)

**当前 `remember` 是纯 append,从不修改、从不汇总:**
- 没有去重 — 反复说"我用 vim"会留多条
- 没有更新 — 用户改主意了(vim → emacs)旧条目不会改
- 没有 forget / delete 工具
- 没有 consolidate / summarize — 跑久了 MEMORY.md 会膨胀,system prompt 越来越大
- 唯一"修改"路径:`/memory clear` 核选项,或手动 `vim` 编辑

**v0.7.1 的最小补丁建议**(留作未来):
1. `update_memory(match, new_content)` 工具
2. `forget(match)` 工具
3. `/memory consolidate` 命令(LLM 把整份 MEMORY.md 去重汇总写回)
4. 启动时 warning:MEMORY.md > 50 行 → 提示 consolidate

工业方案(2026):
- mem0 / Letta:写入时即时 dedup + conflict-resolve
- Claude Code:per-memory `.md` 文件 + 索引,LLM 用 Edit 工具维护单条记忆

## 我的补充(待你填)

- 这个 iter 哪里让我感觉特别重要?
- 哪里让我特别困惑?
- 我想再深挖什么?
- 我跑过哪些任务,记忆系统真的帮上忙了?
- 有没有撞到上面 Known Limitation 中的某条?
