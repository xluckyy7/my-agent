# Iter 6 retro — web 工具(fetch + search)

**Tag:** `v0.6`
**Window:** 2026-05-20 ~ 2026-05-20
**核心交付:** `web_fetch_tool`(URL → 提取正文)+ `web_search_tool`(Tavily,可选)。agent 从此能上网查 / 读。

---

## 做了什么

- 新依赖:`httpx>=0.27`,`trafilatura>=1.12`
- `src/my_agent/tools/web.py`:
  - `_fetch(args)` — httpx.Client(15s timeout + follow_redirects + 浏览器 User-Agent)
  - HTML 用 trafilatura 提取主体(剥 nav / footer / 广告 / 评论);非 HTML 直传原文
  - `max_chars` 默认 8000,超出截断 + `[truncated at N chars]` 标记
  - HTTP 4xx/5xx 抛 RuntimeError → ToolRegistry 兜底转 is_error
- `web_search_tool`(可选,需 `TAVILY_API_KEY`):
  - POST `https://api.tavily.com/search`,带 query / max_results / include_answer
  - 输出 `Direct answer + 编号 results(title/url/snippet)`
- **条件注册**:`build_registry` 检查 `TAVILY_API_KEY`,有才注册 `web_search`,模型在 schemas 里看不到不可用工具
- 16 新测试(9 fetch + 7 search),累计 175 unit

## 关键决策与原因

- **trafilatura 而非自写 HTML 解析** — 业界标准 boilerplate 提取,处理新闻/博客/文档站效果好。学习项目用对的轮子比造轮子更值。
- **fallback:trafilatura 提取空 → 返原始 HTML** — 短页面 / 异常布局可能让提取器失败,有总比没好。
- **DEFAULT_HEADERS 含浏览器 UA** — 太多站点 block 默认 httpx UA(`python-httpx/x.y`),换 `Mozilla/5.0 ...` 访问率高一截。
- **web_search 条件注册** — 没 TAVILY_API_KEY 时直接不 register,模型在 schemas 看不到这个工具,不会幻觉去调它。专门 2 个测试覆盖。
- **Tavily 而非 DuckDuckGo / Google scraping** — DuckDuckGo HTML 易被封,Google 完全反爬。Tavily 是 2026 agent 生态主流(为 LLM 设计 / 免费 1000 月)。
- **`web_search` 输出包含 `DIRECT ANSWER`** — Tavily 的 RAG answer 字段,常常比 search results 更直接有用。

## 学到的关键概念

- **Tool selection 是 prompt engineering 的延伸** — 第一次让 agent "拉 HN 首页前 3 标题",它选了 `run_bash + curl` 而非 `web_fetch`。原因:system prompt 提到"run shell commands"更突出,且 curl 是它训练里"工程师默认动作"。**给模型多个工具时,description 措辞和"显著性"会影响选择**。要强制用某工具就在 description 里写得更具体(`PREFER this over shell curl`)。
- **条件注册是 capability gating 的简洁实现** — agent 框架里"某工具需要密钥/某 admin 用"是常见需求。**最干净处理:在 build_registry 时按条件决定要不要 register**。比"工具内部 raise" 干净 — 模型永远看不到不可用工具。
- **trafilatura 把 30 年 HTML 抓取痛史封装成一行 `extract()`** — 这是"挑对开源轮子"的胜利。
- **httpx 比 requests 在 agent 系统里更适合** — `with Client() as c:` 显式生命周期 + 同步异步同 API + timeout 默认 enabled。新项目直接 httpx 跳过 requests。
- **mock httpx 比 mock requests 略复杂**(Client 是 context manager)— 我们直接 mock `Client.get` / `.post` 简化,工业项目可考虑 `respx`。

## 踩的坑 / 让我意外的地方

- 初次 demo 模型不用 web_fetch 选了 curl,我以为是工具失效,实际是 prompt 引导问题。这次"反直觉的选择"反而暴露了 prompt 设计这件事。
- Tavily 的 `include_answer=True` 参数偶尔被它"懒"返回空字符串,我们的 `if answer.strip()` 守护住了。

## 我的补充(待你填)

- 这个 iter 哪里让我感觉特别重要?
- 哪里让我特别困惑?
- 我想再深挖什么?
- 我用 v0.6 跑过哪些真实 web 任务?哪些卡了?
