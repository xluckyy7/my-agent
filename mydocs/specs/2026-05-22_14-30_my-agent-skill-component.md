# Feature Spec: my-agent skill 组件(仿 Claude Code skills)

**Spec Type**: Feature Spec
**Created**: 2026-05-22 14:30
**Phase**: [PRE-RESEARCH → RESEARCH]
**Status**: [LOCKED]
**Approval**: NOT_APPROVED
**Owner**: 用户(xinqi)

---

## 0. Meta

- **Final Goal**: 给 my-agent 加一个 **skill 系统**,行为模型对齐 Claude Code skills(procedural guidance,纯文本 SKILL.md,model 主动激活)
- **Final Scope (用户明确)**: **本次只产出 Research + 设计文档 + Plan,不动代码**(不进入 Execute)
- **Exit Criteria**: Spec 完整含 Plan(File Changes / Signatures / Checklist),通过 advisory `REVIEW SPEC`,等待用户后续是否 `Plan Approved` 来决定 Execute

---

## 1. Goal / In-Scope / Out-of-Scope

### 1.1 Goal
让 my-agent 用户可以在 `~/.my-agent/skills/<skill-name>/SKILL.md` 写一段 procedural guidance,启动 my-agent 时自动 load,LLM 在对话中识别到 trigger 描述时能主动激活并按 SKILL.md 走流程 — 整体行为跟 Claude Code 的 skill 一致。

### 1.2 In-Scope (本次 Plan 覆盖)
- skill **目录约定**: `~/.my-agent/skills/<name>/SKILL.md` + 可选附属文件(scripts/ references/ assets/)
- skill **加载机制**: 启动时 scan, parse frontmatter(name / description / 触发关键词)
- skill **元信息注入**: 把所有 skill 的简短描述 inject 到 system prompt(让 model 知道有什么 skill 可激活)
- skill **激活协议**: 用 tool-call 模式 — 加 1 个 built-in tool `invoke_skill(name)`,model 调它时把对应 SKILL.md 全文作为 tool_result 返回(类似 Claude Code 的 Skill 工具)
- 跟现有 5 类扩展(tools / hooks / plugins / MCP / memory)的**边界关系**说明
- **完整文档**: SKILL.md frontmatter schema、目录约定、示例 skill、failure mode、安全考虑
- **测试设计草案**(只写测试矩阵,不实现):加载 / 缺 frontmatter / 触发注入 / invoke 调用

### 1.3 Out-of-Scope (本次明确不做)
- **不实现代码**(用户明确)
- 不做 skill marketplace / 远程安装(对齐 CC 的 `@anthropic-skills` 那种生态先不做)
- 不做 skill 内部的可执行脚本支持(只 procedural 纯文本)
- 不做 skill 之间的依赖图 / 版本管理
- 不动现有 hooks / plugins / tools 架构(skill 是新加的并列扩展点)

---

## 2. Open Questions
- [TBD-1] SKILL.md frontmatter 用 YAML(对齐 CC)还是简化成 JSON?
- [TBD-2] 用户/项目级 skill 优先级:`~/.my-agent/skills/` vs `./.my-agent/skills/`?
- [TBD-3] invoke_skill 后 SKILL.md 全文进 conversation 还是 system prompt?(影响 context cost)
- [TBD-4] skill 内引用的 references/*.md 怎么暴露(model 需要 read_file 自取 vs 自动 inject)
- [TBD-5] 跟 sub-agent(task tool)如何交互 — sub-agent 能否激活 skill?

---

## 3. Context Sources
- Claude Code skill 实际行为(我自己运行在 CC 里,system prompt 列出了一堆 skill)
- my-agent 现状: `src/my_agent/cli/main.py` (boot wire) / `agent/memory.py` (system prompt 注入) / `agent/loop.py` / `tools/base.py` / `agent/hooks.py` / `plugins/`
- 用户已经在用 `.claude/skills/` 写自己的 skill(`sycm-*` / `aone-*` 这些)— 可以反向看 CC 的实际 SKILL.md 长什么样

---

## 4. Next Actions (immediate)
- [ ] [RESEARCH] 调研 Claude Code skill 行为模型(context7 + 看用户机器上 ~/.claude/skills/ 实样)
- [ ] [RESEARCH] my-agent 启动 wire + system prompt 注入 + tool 注册的现状梳理
- [ ] [INNOVATE] 至少 2 设计方案(静态 inject vs invoke-on-demand vs hybrid)+ tradeoff
- [ ] [PLAN] 详细 design: 文件路径 / 函数签名 / 原子 checklist
- [ ] [REVIEW SPEC] advisory pre-execute review,GO/NO-GO 建议
- [ ] 等用户 `Plan Approved` 才进 Execute(本次预期不进)

---

## 5. Research Findings

### 5.1 Claude Code skill 行为模型(实证)

直接读了 `~/.claude/skills/` 下多个真实 skill(a1 / brainstorming / generate-image / sdd-riper-one / skill-creator)+ 当前会话的 system prompt(我自己在 CC 里跑)。

**目录约定**:
```
~/.claude/skills/<skill-name>/
  ├── SKILL.md          (必需)
  ├── references/       (可选 — model 用 Read 自取)
  ├── scripts/          (可选 — Bash 调)
  ├── assets/           (可选)
  └── agents/           (可选)
```

**SKILL.md frontmatter schema(YAML,`---` 分隔)**:
| 字段 | 必/可 | 用途 |
|---|---|---|
| `name` | 必 | 唯一标识 (kebab-case) |
| `description` | 必 | 一段话同时说明"做什么 + 何时用",**就是 trigger 信号本身**(model 看这个决定激活) |
| `version` | 可 | 版本字符串 |
| `author` | 可 | 作者 |
| `allowed-tools` | 可 | 限制 skill 内允许的工具(权限收缩) |
| `compatibility` | 可 | 依赖说明(如 "requires: gh CLI") |

**关键洞察**: 没有"trigger keywords" 单独字段 — description 自然语言就是 trigger。CC 文档明确说"description 是 primary triggering mechanism",建议写得"pushy"对抗 undertriggering(skill-creator 原话)。

**加载 / 激活协议**:
1. **启动加载**: CC scan `~/.claude/skills/*/SKILL.md`,只读 frontmatter,把 `name + description` 列进 system prompt 的 `<available-skills>` 段(我当前 session 的 system 末尾就有)
2. **激活**: model 主动调 built-in `Skill` tool,params `{ skill: "<name>", args?: "..." }`
3. **执行**: Skill tool 把整个 SKILL.md body 作为 tool_result 返回到 conversation(不动 system prompt)
4. **References lazy load**: model 按 SKILL.md 里的指引,用 Read tool 主动读 `references/*.md`

**性能优化**:
- 启动加载只读 frontmatter — 几十个 skill 总开销也只是几 KB
- SKILL.md body 只在 model 决定激活时才进 context(context cost 按需付出)
- skillListingMaxDescChars / skillListingBudgetFraction 是 CC 的 trim 设置(default 1536 char / 1% context)

### 5.2 my-agent 现状(扩展点全景)

| 扩展点 | 加载 | 暴露给 model 的形式 | 触发 |
|---|---|---|---|
| **tools** | `cli/main.py:_collect_base_tools` + MCP scan | tool schemas(注入到 `chat.completions.create(tools=...)`) | model 主动 `tool_call` |
| **hooks** | `agent/hooks.load_hooks` 读 `~/.my-agent/hooks.json` | 不暴露给 model — 内部触发 | 框架内部 `_fire()` |
| **plugins** | `~/.my-agent/hooks.json` 的 python type hook 引用 | 同上,内部 | 同上 |
| **MCP** | `mcp_layer/config.load_mcp_config` 读 `~/.my-agent/mcp.json` → 包成 tools | 同 tools | 同 tools |
| **memory** | `agent/memory.load_project_memory + load_user_memory` | inject 进 system prompt(`compose_system_prompt` 第 2/3 段) | model 自然 follow |

**关键 join points(给 skill 系统插桩)**:

1. **`agent/memory.compose_system_prompt(base, project, user)`** — 现在拼"base + project + user" 3 段,加 skill 就是加第 4 段 `"## Available Skills"` 列出 name + description
2. **`cli/main.py app()` 启动 wire** — 在调 `compose_system_prompt` 前加一步 `load_skills(home)` 拿 SkillRegistry,把 listing 传进去
3. **`cli/main.py _collect_base_tools()`** — 加一个 `make_invoke_skill_tool(registry)` 工厂 tool,model 调它时 read SKILL.md body 返回
4. **`agent/loop.py` / `tools/base.py`** — 不动,完全复用现有 tool dispatch

### 5.3 跟现有扩展的边界

| 维度 | tools | memory | skill (新) |
|---|---|---|---|
| **谁写的** | 项目内核 + MCP server 作者 | 用户 + LLM(remember 工具) | **用户 + skill 作者(可分发的 .md 包)** |
| **内容形态** | Python 函数 + JSON schema | 纯 Markdown,人工沉淀的事实 | **纯 Markdown,procedural guidance + 元信息** |
| **何时 inject** | tools schema 启动时常驻 | 内容启动时常驻 system | **listing 启动常驻 + body 按需(invoke_skill 才入 conv)** |
| **激活

---

## 6. Architecture & Strategy (Innovate)
*(Innovate 阶段填)*

---

## 7. Detailed Design & Implementation (Plan)
*(Plan 阶段填)*

---

## 8. Spec Review Notes (advisory)
*(REVIEW SPEC 后填)*

---

## 9. Resume / Handoff
- 当前 phase: PRE-RESEARCH → 进 RESEARCH
- 当前 spec path: `mydocs/specs/2026-05-22_14-30_my-agent-skill-component.md`
- new chat 续接:读本文件 §0–§4 + 用户最初 prompt "我要给这个 agent 新增 skill 组件" + 已确认决策(仿 CC + 不动代码)
