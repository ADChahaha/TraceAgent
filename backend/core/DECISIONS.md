# backend/core 关键决策

归属 [Backend 设计](../docs/DESIGN.md)，记录数据库连接管理与核心基础设施的长期取舍。

## 1. 使用 `ThreadLocalDatabase` 按线程隔离 SQLite 连接

- 决定：SQLite 连接管理采用 `ThreadLocalDatabase`，为每个工作线程（主线程与 `asyncio.to_thread` 线程池线程）按需创建并缓存独立的 `sqlite3.Connection`，统一开启 `WAL` 模式、`foreign_keys = ON` 与 `busy_timeout = 30000`，应用关闭时统一回收所有连接；不在多个工作线程之间共享单一文件库连接实例。
- 原因：多工作线程共享同一个 `sqlite3.Connection`（即便开启 `check_same_thread=False`）在并发读写时会触发 `sqlite3.InterfaceError` 与 `IndexError`，造成查询错乱或误报会话不存在。
- 排除：在请求线程与后台工作线程间共享全局单一 `sqlite3.Connection` 实例。

## 2. 边界显式拒绝 `:memory:` 等内存数据库路径

- 决定：`validate_database_path` 在 `BackendSettings`、`ThreadLocalDatabase` 与 `connect_database` 入口统一校验 `database_path`，显式拒绝 `:memory:`、空路径、`.`/`..`、目录路径以及 `file:` / `mode=memory` SQLite URI，立即抛出 `ValueError`；测试与 CI 冒烟统一使用临时目录中的普通 SQLite 文件库。
- 原因：按线程独立 `sqlite3.connect(":memory:")` 会让主线程建表与工作线程恢复落入彼此隔离的空内存库，导致启动崩溃（`no such table: chat_sessions`）；而实测 SQLite 命名共享内存库（`file:...?mode=memory&cache=shared`）在多线程并发读写下会直接触发不受 `busy_timeout` 保护的 `database table is locked` 错误，且内存库不支持 WAL。`backend` 的真实运行、单测与 CI 均无使用 `:memory:` 的需求，边界显式拒绝可以彻底消除隐含启动雷。
- 排除：对 `:memory:` 退回跨线程共享单连接；使用 SQLite `mode=memory&cache=shared` 命名共享内存库；为 `:memory:` 单独引入全局锁连接代理。
