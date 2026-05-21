# 多 Agent 框架学习路线

> 整理日期：2026-05-21
> 目标：用最少的弯路掌握多 Agent 系统的核心抽象与主流框架

学习顺序的核心原则：**先概念 → 后框架；先单 Agent → 后编排；先直观 → 后复杂**。

---

## 阶段 0：先打地基（1-2 周，别跳过）

不学框架，只学**底层抽象**——否则学任何框架都是抄 demo。

- **ReAct**（Reasoning + Acting 循环）：所有 Agent 的祖宗
- **Function Calling / Tool Use**：直接用 OpenAI / Claude SDK 写一个能调工具的循环
- **MCP（Model Context Protocol）**：跑通一个 MCP server + client，理解"工具是怎么挂上去的"

**产出**：手写一个 50 行的 ReAct loop，能查天气、做计算。
**这一步做完，你看任何框架都不再迷糊**。

---

## 阶段 1：CrewAI（1 周）—— 入门首选

**为什么先它**：Role + Task + Crew 的心智模型最贴近人类协作，几十行代码就能跑出多 Agent 效果，**不需要先理解状态图**。

**核心概念**：
- Role（角色）
- Task（任务）
- Sequential vs Hierarchical Process
- Tool 共享机制

**做完一个项目就走**——别陷进去，CrewAI 天花板较低、控制力不够。

---

## 阶段 2：LangGraph（2-3 周）—— 真正的核心

**为什么放这里**：工业界目前**最值得深学**的框架。思想是图 + 状态 + 检查点。
**学完它，再看其他框架都是它的子集或变体**。

**学习顺序**：

1. State + Node + Edge 基础图
2. 条件边、循环、子图
3. **Supervisor 模式**（监督者编排）
4. **Swarm 模式**（去中心化交接）
5. Checkpointing、Human-in-the-loop、Time travel
6. Streaming + 可观测性（LangSmith）

**产出**：用同一个业务，分别用 Supervisor 和 Swarm 实现一遍，体会差异。

---

## 阶段 3：OpenAI Agents SDK（3-5 天）—— 对照学

学完 LangGraph 再看它会很快。重点理解：

- **Handoff 语义**和 LangGraph Swarm 的对应关系
- **Guardrails**（输入输出护栏）
- 它怎么把"复杂"藏起来——这是写好 Agent API 的设计参考

---

## 阶段 4：选一条深入路径（二选一即可）

### A. 企业生产方向 → Microsoft Agent Framework (MAF)

- Magentic 编排模式
- **Durable Workflows**（长时任务、重启恢复）
- 与 Azure / AutoGen 旧代码的迁移

### B. 研究型 / 长任务方向 → DeepAgents

- Planner + Sub-agents 的上下文隔离
- 虚拟文件系统作为长期记忆
- 适合"AI 研究员""深度写作"类任务

---

## 阶段 5：协议层与跨框架（按需）

只在你要做**跨厂商 / 跨团队 Agent 互通**时才学：

- **A2A 协议**：Agent Card、能力发现、委托
- **ACP**：异步事件驱动的协作总线
- **ANP / AgentNet**：身份、信誉、结算

---

## 一句话路线图

```
ReAct + MCP (基础)
   ↓
CrewAI (建立直觉, 1 周)
   ↓
LangGraph (吃透核心, 2-3 周) ← 最重要
   ↓
OpenAI Agents SDK (对照, 几天)
   ↓
MAF 或 DeepAgents (按方向选一)
   ↓
A2A / ACP (跨厂商互通时再学)
```

---

## 几个常见坑

- **不要从 AutoGen 学起**：已被微软合并进 MAF，文档与生态都在迁移。
- **不要一开始就追协议**：MCP/A2A 是抽象层，没写过 Agent 的人学协议会学得很空。
- **不要五个框架都浅尝**：LinkedIn 上"5 框架同流水线"测试只有 2 个跑通的原因是——浅学谁都跑不通。**深学一个，胜过浅学五个**。
- **每阶段都要有产出物**：能跑、能 demo 的小项目比看 100 篇文章都强。

---

## 配套：2026 多 Agent 架构全景速览

### 三种主导编排范式

1. **Orchestrator-Worker（监督者）** — 中央 Orchestrator 拆任务、分派 worker、汇总结果
   代表：Anthropic Research、Magentic-One、LangGraph Supervisor
2. **Hierarchical（层级式）** — Supervisor 之下再嵌 Supervisor
   代表：LangGraph、CrewAI Crews
3. **Swarm / Handoff（去中心化）** — Agent 间按需 handoff，无中心
   代表：OpenAI Swarm、CrewAI Flow

新涌现：**Parallel Agentic Workflow（APWA）** — DAG 并行化 worker，解决 Magentic-One 串行瓶颈。

### 框架对比

| 框架 | 架构核心 | 强项 | 适用场景 |
|---|---|---|---|
| LangGraph | 显式有状态图 | 控制流可编程、检查点/中断/回放 | 复杂长链路、需要人审 |
| MAF (Microsoft) | Magentic + Durable Workflows | Azure 原生、企业治理 | 大型企业生产 |
| OpenAI Agents SDK | Handoff + Guardrails | 与 GPT 深度整合、轻量 | OpenAI 生态快速落地 |
| CrewAI | Role-based Crew + Flow | 角色/任务建模直观、上手快 | 业务流程类应用 |
| DeepAgents | Planner + Sub-agents + FS | 长任务规划、子代理隔离 | 研究/写作类深度任务 |

### 协议口诀

**MCP 管"Agent 用工具"，A2A 管"Agent 找 Agent"，ANP 管"Agent 信谁、跟谁结算"。**

---

## 参考资料

- [LangGraph vs CrewAI vs OpenAI Agents SDK: 2026 Guide](https://www.codebridge.tech/articles/choosing-a-multi-agent-framework-langgraph-crewai-microsoft-agent-framework-or-openai-agents-sdk)
- [Microsoft Agent Framework (GitHub)](https://github.com/microsoft/agent-framework)
- [Multi-Agent 多智能体协作系统：架构原理、框架选型与实战指南](https://cloud.tencent.com/developer/article/2649756)
- [MCP、ACP、A2A：AI Agent 三大协议](https://gitcode.csdn.net/6a0b01c410ee7a33f2738489.html)
- [ai-agents-from-zero（didilili）](https://github.com/didilili/ai-agents-from-zero)
- [Agent Harness Engineering 综述（CMU/耶鲁）](https://news.qq.com/rain/a/20260519A02F5Y00)
