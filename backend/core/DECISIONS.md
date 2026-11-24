# backend/core 关键决策

归属 [Backend 设计](../docs/DESIGN.md)，记录数据库连接管理与核心基础设施的长期取舍。

## 1. 使用 `ThreadLocalDatabase` 按线程隔离 SQLite 连接

- 决定：SQLite 连接管理采用 `ThreadLocalDatabase`，为每个工作线程（主线程与 `asyncio.to_thread` 线程池线程）按需创建并缓存独立的 `sqlite3.Connection`，统一开启 `WAL` 模式、`foreign_keys = ON` 与 `busy_timeout = 30000`，应用关闭时统一回收所有连接；不在多个工作线程之间共享单一文件库连接实例。
- 原因：多工作线程共享同一个 `sqlite3.Connection`（即便开启 `check_same_thread=False`）在并发读写时会触发 `sqlite3.InterfaceError` 与 `IndexError`，造成查询错乱或误报会话不存在。后续修复 `BACKEND_DATABASE_PATH=":memory:"` 跨线程缺表缺陷时，仅应对内存库做特例处理，不可把文件库回退为跨线程共享单连接。
- 排除：在请求线程与后台工作线程间共享全局单一 `sqlite3.Connection` 实例。
