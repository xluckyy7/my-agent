# Linux I/O 多路复用与 epoll 内核原理笔记

> 理解 asyncio 事件循环底层运作机制,从硬件中断到 epoll_wait 返回的完整链路。

---

## 1. 硬中断与软中断

### 为什么要分两阶段

硬中断期间 CPU **关闭中断响应**(cli 指令),不再响应任何新中断。  
如果在硬中断里做完全部工作(协议栈解析、数据拷贝、进程唤醒),时间过长会导致:

- 其它设备中断被屏蔽 → 键盘/磁盘/网卡不响应
- 定时器中断丢失 → 系统时钟漂移、调度延迟
- 网卡 ring buffer 溢出 → 丢包

因此内核把中断处理拆成"上半部 + 下半部":

```
硬中断(上半部, top half):
    ① 搬走硬件数据(防覆盖)
    ② 设置软中断标志
    ③ 打开中断,立即返回
    耗时: < 1μs

软中断(下半部, bottom half):
    ① TCP/IP 协议栈解析
    ② 数据拷贝到 socket 接收缓冲区
    ③ 触发 epoll 回调 + 唤醒进程
    耗时: 10~100μs, 但此时中断是开着的!
```

### 硬中断 vs 软中断

| 维度 | 硬中断 | 软中断 |
|---|---|---|
| 触发方 | 硬件电信号 | 代码设置标志位 |
| 执行时机 | 立刻(抢占一切) | 延迟到合适时机 |
| 能否被打断 | 不能(关中断) | 能被硬中断打断 |
| 执行时长 | 极短(μs) | 较长(处理协议栈) |
| 能否睡眠 | 不能 | 不能(仍在中断上下文) |
| 能否在多核分担 | 绑定收到信号的核 | 可分配到不同核 |

### NAPI: 减少中断次数

高流量下每包一次硬中断太频繁(10万次/秒),NAPI 机制:

```
第1个包 → 硬中断 → 关闭网卡后续中断 → 切换到 poll 模式
后续包 → 软中断里主动 poll 网卡(budget=64, 一次取64个包)
取完 → 重新打开网卡中断

10万包/秒: 传统=10万次硬中断, NAPI≈1500次硬中断
```

---

## 2. epoll 内核数据结构

### 两个核心结构

```
epoll 实例 (epoll_create 创建)
├── 红黑树 (rbr)           ← 存储所有注册的 fd
│   epoll_ctl(ADD/DEL/MOD) 时查找: O(log n)
│
└── 就绪链表 (rdllist)     ← 存储"有事件发生"的 fd
    数据到达时回调加入: O(1)
    epoll_wait 时直接返回: O(就绪数)
```

### 注册阶段: epoll_ctl(ADD) — O(log n)

```c
int epoll_ctl(epfd, EPOLL_CTL_ADD, fd, event) {
    // 创建 epitem 节点
    epi = kmalloc(sizeof(struct epitem));

    // 插入红黑树 → O(log n)
    ep_rbtree_insert(ep, epi);

    // 关键:在 socket 上注册回调
    // 当数据到达时,内核调这个回调
    epi->wait.callback = ep_poll_callback;
    add_wait_queue(socket->sk_wq, &epi->wait);
}
```

### 事件到达: ep_poll_callback — O(1)

当软中断处理完 TCP 数据后:

```c
static int ep_poll_callback(wait_queue_entry_t *wait) {
    struct epitem *epi = container_of(wait, ...);

    // O(1): 直接挂到就绪链表尾部
    list_add_tail(&epi->rdllink, &ep->rdllist);

    // 唤醒阻塞在 epoll_wait 的进程
    wake_up(&ep->wq);
}
```

没有遍历,没有查找——socket 的回调直接把自己加入就绪链表。

### epoll_wait: 只返回就绪的

```c
int epoll_wait(epfd, events, maxevents, timeout) {
    // 就绪链表为空 → 睡眠(让出 CPU)
    while (list_empty(&ep->rdllist))
        schedule_timeout(timeout);

    // 醒来:只拷贝就绪的 fd 到用户空间
    for_each(epi, &ep->rdllist) {
        events[count++] = epi->event;
        if (count >= maxevents) break;
    }
    return count;  // 返回 0 ~ maxevents 个
}
```

---

## 3. epoll vs select 对比

| 维度 | select/poll | epoll |
|---|---|---|
| 注册方式 | 每次调用传全部 fd 列表 | 一次注册(epoll_ctl),持久有效 |
| 内核检测 | 遍历所有 fd 逐个检查 O(n) | 回调自动加入就绪链表 O(1) |
| 返回结果 | 返回全部 fd + ready 标记(用户自己扫) | 只返回有事件的 fd |
| 10000 连接 3 个就绪 | 扫 10000 个找 3 个 | 直接给 3 个 |
| fd 数量限制 | select: 1024(FD_SETSIZE) | 无硬限制(epoll_create) |
| 用户→内核拷贝 | 每次调用全量拷贝 | 只在注册时拷贝一次 |

---

## 4. 一次 epoll_wait 返回多个 fd

一次 epoll_wait 不是只返回一个 fd:

### 原因一: 软中断批量处理

NAPI 一次 poll 可取 64 个包 → 多个 socket 同时就绪 → 多个 ep_poll_callback 被调用 → 多个 epitem 加入就绪链表。

### 原因二: 睡眠期间积累

```
线程 epoll_wait 睡觉
    T1: socket A 收到数据 → A 加入就绪链表,唤醒线程
    T1+ε: socket B 也收到 → B 也加入链表 (线程还没被调度到)
    T1+2ε: socket C 也收到 → C 也加入链表
线程被调度执行 → epoll_wait 返回 {A, B, C}
```

### 原因三: maxevents 参数

```c
int n = epoll_wait(epfd, events, maxevents=128, timeout=-1);
// n 可以是 0(超时), 1, 50, 128
// 超过 maxevents 的留在链表,下次取
```

---

## 5. 事件循环不是"轮询"

```python
# asyncio 事件循环核心 (伪代码)
while not stopping:
    events = selector.select(timeout)     # ← epoll_wait, 阻塞!
    for key, mask in events:              #   没事时 CPU 休眠
        key.data.callback(key.fileobj)    #   有事时只处理就绪的
    run_ready_callbacks()                 # ← call_soon 安排的回调
```

**不是忙等(busy poll),是阻塞等待(block wait)**:
- 没有 I/O 事件 → 线程挂起, CPU 去干别的
- 有事件 → 内核唤醒线程,只返回就绪的 fd
- 更像"睡觉等闹钟",不像"每秒看一次表"

---

## 6. 完整链路: 从网卡到协程恢复

```
① 网卡收到数据包
    ↓ 硬件中断 (< 1μs)
② 网卡驱动: 标记"有包" + 触发 NET_RX_SOFTIRQ + 关网卡中断
    ↓ 硬中断返回, CPU 恢复响应其它中断
③ 软中断: NAPI poll 批量取包(一次最多 64 个)
    ↓ 每个包走 TCP/IP 协议栈
    ↓ 数据放入 socket 接收缓冲区
④ 调用 ep_poll_callback → O(1) 加入 epoll 就绪链表
⑤ 唤醒阻塞在 epoll_wait 的事件循环线程
⑥ epoll_wait 返回就绪列表(可能多个 fd!)
⑦ 事件循环遍历 → 调用每个 fd 对应的 callback
⑧ callback 内部 coro.send(None) → 协程恢复执行 → 你的业务代码拿到数据
```

---

## 7. 各平台 I/O 多路复用

| 平台 | 机制 | asyncio 使用 |
|---|---|---|
| Linux | epoll | `selectors.EpollSelector` |
| macOS/BSD | kqueue | `selectors.KqueueSelector` |
| Windows | IOCP | `ProactorEventLoop` |
| Linux 5.1+ | io_uring | 需第三方库(如 uvloop 实验性支持) |

Python `selectors` 模块自动选当前 OS 最优方案。

---

## 总结

```
硬中断只标记不处理  → 因为关中断期间所有设备不响应,必须极快返回
epoll O(1) 在哪     → 不在注册(O(log n)红黑树),在事件到达时回调直接挂链表
一次返回多个 fd     → NAPI 批量收包 + 睡眠积累 + maxevents 上限
事件循环不是轮询    → 是 epoll_wait 阻塞等待,内核中断链路驱动唤醒
```
