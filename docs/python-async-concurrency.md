# Python 异步与并发模型笔记

> 基于 my-agent 项目 MCP client 层的实际代码(`src/my_agent/mcp_layer/client.py`)总结。

---

## 1. 同步函数里为什么没法直接写 `await`

### 编译期限制

`await` 只在 `async def` 函数内合法。Python 编译器看到 `await` 会生成**协程专用字节码**(`GET_AWAITABLE` + `YIELD_FROM`),这些字节码只有协程对象的执行帧才能运行。

```python
async def ok():
    result = await some_io()   # ✅ 编译通过,生成协程字节码

def bad():
    result = await some_io()   # ❌ SyntaxError: 'await' outside async function
```

### 运行时原因

`await` 的语义是"**把控制权交还给事件循环**"。如果你在一个同步函数里——同步调用栈中根本没有事件循环在驱动——"交还"无处可去,"唤醒"也无人触发。

| 执行模型 | 遇到 I/O 时 | 恢复方式 |
|---|---|---|
| 同步函数 | 线程阻塞(OS 挂起) | OS 调度器唤醒 |
| async 函数 | `await` 挂起协程 | 事件循环通过 `coro.send(None)` 唤醒 |

### 比喻

- 同步 = 你排队站着等叫号,人在原地不动
- async = 你拿了号去坐着,叫到再来
- `await` = "我先退一步,叫号机叫我再回来"
- 如果没有叫号系统(事件循环),说"等叫到我"毫无意义

---

## 2. `asyncio.run()` 内部做的事

### 一句话

> 在同步线程里**临时搭建一个异步世界**,跑完一个协程,把结果拿回来,然后销毁那个异步世界。

### 源码简化

```python
def run(main):
    # ① 检查:不允许嵌套(当前线程不能已有运行中的循环)
    if _get_running_loop() is not None:
        raise RuntimeError("cannot nest asyncio.run()")

    # ② 创建全新事件循环
    loop = asyncio.new_event_loop()

    try:
        # ③ 核心:同步阻塞地跑协程直到完成
        return loop.run_until_complete(main)
    finally:
        # ④ 清理:取消残留 Task
        _cancel_all_tasks(loop)
        # ⑤ 关闭 async generators
        loop.run_until_complete(loop.shutdown_asyncgens())
        # ⑥ 关闭 executor
        loop.run_until_complete(loop.shutdown_default_executor())
        # ⑦ 销毁循环
        loop.close()
```

### `run_until_complete` 的内部

```python
def run_until_complete(self, future):
    task = ensure_future(future)          # 协程 → Task
    task.add_done_callback(stop_loop)      # 完成时停循环

    self.run_forever()                     # 事件循环开始转:
    # ↓ 内部循环
    # while not stopping:
    #     events = epoll.poll(timeout)     # 等 I/O 就绪
    #     for event in events:
    #         event.callback()             # 推进相关 Task
    #     run_ready_callbacks()            # 跑就绪的协程

    return task.result()
```

### 项目中的对应

```python
def fetch_tools_sync(spec):
    async def _go():
        session = await _open_session(spec)   # 启动 MCP 子进程
        resp = await session.list_tools()      # stdio 通信
        await _close_session(session)          # 关闭子进程
        return results
    return asyncio.run(_go())   # 同步世界 → 异步世界 → 同步世界
```

每次调用都：创建循环 → 启子进程 → 通信 → 关子进程 → 销毁循环。正确但慢。

---

## 3. Python 进程、线程、协程

### 概念层次

```
操作系统
├── 进程 A (独立内存空间)
│   ├── 主线程 (OS 调度)
│   │   └── 事件循环
│   │       ├── 协程 1 (用户态调度)
│   │       ├── 协程 2
│   │       └── 协程 3...
│   ├── 线程 2 (OS 调度)
│   └── 线程 3
└── 进程 B
    └── ...
```

### 对比矩阵

| 维度 | 进程 (Process) | 线程 (Thread) | 协程 (Coroutine) |
|---|---|---|---|
| 调度者 | OS 内核 | OS 内核 | 用户代码(事件循环) |
| 切换成本 | 高 (~ms) | 中 (~μs) | 极低 (~ns) |
| 内存隔离 | 完全隔离 | 共享堆,各有栈 | 共享一切 |
| 并行能力 | 真并行(多核) | GIL 限制: 不能真并行 CPU 任务 | 单线程, 不并行但能并发 I/O |
| 可创建数量 | ~百 | ~千 | ~百万 |
| 通信方式 | IPC(管道/socket) | 锁/队列 | 直接共享变量 |
| 死锁风险 | 有 | 有 | 无(协作式) |
| 适合场景 | CPU 密集 | I/O密集(有GIL限制) | I/O 密集(最优) |
| Python API | `multiprocessing` | `threading` | `asyncio` |

### GIL 的影响

```
多进程: ✅ 绕过 GIL(独立解释器) → 真并行 CPU
多线程: ❌ GIL 只允许一个线程执行字节码 → CPU 密集假并行, I/O 等待时释放
协程:   🤷 单线程, GIL 无影响 → I/O 并发最优
```

### Python 并发策略选择

```
网络/数据库 I/O 密集 → asyncio (协程)
文件 I/O 密集        → threading (GIL 在 I/O wait 时释放)
CPU 密集计算         → multiprocessing (绕 GIL, 真并行)
```

### 协程为什么对 I/O 密集特别高效

```python
# 线程方式: 10000 并发请求 = 10000 线程 = ~80GB 栈内存(每线程默认8MB)
# 实际: 上千线程时 OS 调度开销巨大

# 协程方式: 10000 并发请求 = 10000 协程 = ~几 MB
# 实际: 一个线程 + 一个 epoll, 内核只管网络事件, 用户态调度协程
async def main():
    tasks = [asyncio.create_task(fetch(url)) for url in urls]
    await asyncio.gather(*tasks)   # 10000 个请求并发执行
```

---

## 4. 整体改异步 vs 当前同步

### 当前同步架构

```
main() ─── sync ──→ AgentLoop ─── sync ──→ LLMClient.stream()
                       │                       │
                       │ sync                  │ sync (httpx)
                       ▼                       ▼
                  ToolRegistry.call()    openai.ChatCompletion.create()
                       │
                       │ asyncio.run() ← 每次新建循环
                       ▼
                  MCP 子进程通信 (async)
```

### 整体异步架构(目标)

```
asyncio.run(main())  ← 最外层只调一次
    │
    ▼
async main() ─→ AgentLoop ─→ LLMClient.stream()
                    │              │
                    │ await         │ async httpx
                    ▼              ▼
               ToolRegistry   AsyncOpenAI
                    │
                    │ await (直接,无需桥接)
                    ▼
               MCPSession (持久连接,复用)
```

### 收益

| 改进 | 同步(当前) | 异步(目标) |
|---|---|---|
| MCP 连接 | 每次新建/销毁子进程 | 持久连接复用 |
| 多工具调用 | 串行逐个调 | `gather()` 并发调 |
| LLM I/O | 线程阻塞等待 | 等待期间可做别的 |
| 流式+后台 | 不可能 | 一边流式一边准备 |
| 取消/超时 | 不优雅(kill) | `task.cancel()` 优雅中断 |
| 内存/连接 | 每次新进程新连接 | 复用,资源少 |

### 代码对比

```python
# ===== 当前: 串行调用工具 =====
for tc in resp.tool_calls:
    result = self.tools.call(tc.name, json.loads(tc.arguments))  # 逐个阻塞
    conv.append_tool_result(tc.id, tc.name, result)

# ===== 异步: 并发调用工具 =====
results = await asyncio.gather(*[
    self.tools.call_async(tc.name, json.loads(tc.arguments))
    for tc in resp.tool_calls
])  # 三个工具同时调!
```

### 代价

| 维度 | 说明 |
|---|---|
| async 传染性 | `async def` 会一路传染到调用链顶端 |
| 调试复杂度 | stack trace 跨越事件循环,不如同步直观 |
| 测试成本 | 需 `pytest-asyncio`, mock 更复杂 |
| 学习曲线 | 必须理解事件循环、Task、Future |
| 库兼容 | 部分库只有 sync API,需 `run_in_executor` 包装 |

### 渐进式迁移建议

| 阶段 | 方案 | 适合时机 |
|---|---|---|
| 当前 | `asyncio.run()` 桥接 | 学习期,功能验证 |
| 过渡 | 后台线程持久循环 | 需要 MCP 连接复用时 |
| 终态 | 全链路 async | 项目成熟、性能敏感时 |

---

## 5. 三种 async→sync 桥接方式

```python
# 方式 1: asyncio.run() — 简单,每次新循环(当前用的)
def call_sync():
    return asyncio.run(async_work())

# 方式 2: 后台线程持久循环 — 循环常驻,支持连接复用
_loop = asyncio.new_event_loop()
_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_thread.start()

def call_sync():
    future = asyncio.run_coroutine_threadsafe(async_work(), _loop)
    return future.result()   # 阻塞等结果

# 方式 3: 整体 async — 最优,只在最外层 asyncio.run 一次
async def main():
    session = await connect_once()   # 连接只建立一次
    while True:
        await process_turn(session)  # 复用连接

asyncio.run(main())
```

---

## 总结

```
同步代码里不能 await  → 因为没有事件循环驱动"挂起/唤醒"机制
asyncio.run()         → 临时创建事件循环 → 跑协程 → 销毁 (桥接用)
进程/线程/协程         → 分别解决: CPU并行 / OS调度并发 / 用户态I/O并发
全异步的好处           → 连接复用 + 工具并发 + 优雅取消 + 资源节省
全异步的代价           → 传染性 + 调试复杂 + 学习曲线
项目策略              → 学习期保持同步,逐步按需迁移到异步
```
