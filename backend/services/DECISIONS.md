# backend/services 关键决策

归属 [Backend 设计](../docs/DESIGN.md) 与 [SessionManager 架构](../docs/SESSION_MANAGER.md)，记录会话协调、轮次执行与资源流转的长期取舍。

## 1. 两层边界：`SessionManager` 串行命令队列 + `TurnRuntime` 自治执行

- 决定：每个已加载会话拥有唯一 `SessionManager`（通过有界 FIFO 命令队列串行处理创建、取消、上传、删除、订阅等 session 级操作）；每轮执行交由独立 `TurnRuntime` 自治消费 gRPC 流与轮内写入；当前面向单 backend 进程、单用户部署。
- 原因：防止网络流 I/O 阻塞会话级控制命令，同时用结构串行化避免同会话并发上传/删除读改写竞争。
- 排除：在单把锁内同步等待远端模型流，或首版引入多进程分布式 owner 协调与租户鉴权。

## 2. 下发给 agent 的 `resource_path` 只含 bundle，不包含 `raw`

- 决定：下发给 `agent` 的资源定位数组与 `resources.prepared` 载荷只包含 `documents`/`index` bundle 引用，过滤 `raw`；`raw` 仅留在 `chat_resources` 供前端下载、删除与配额校验。
- 原因：`agent` 只消费处理后归档与索引，过滤 `raw` 避免模型或工具误访问原始上传文件。
- 排除：将含 `raw` 的全量会话资源表直接透传给 `agent`。

## 3. 过程事件不落库，损坏 manager 走回收重载而不原地重建

- 决定：流式过程事件（`delta`、`tool_started` 等）仅更新内存 `TurnView` 并广播订阅，不写入数据库；发生数据库事务失败时，通过 `manager.fail()` 标记损坏、取消执行、补发挂起 cancel 并尽力收口，空闲回收后由下次请求重载恢复；重启遗留活跃轮统一标为 `failed`/`backend_restarted`。
- 原因：避免流式过程写放大，同时消除在线原地修复损坏内存态的复杂状态分支。
- 排除：把高频过程事件逐条持久化入库、在线原地重建损坏 manager，或重启后自动重跑遗留问答。

## 4. 会话列表直查数据库，取消只作用于已加载活跃会话

- 决定：`GET /chat/sessions` 直接经 CRUD 读取 SQLite 最近会话，不加载 manager、不创建会话；`POST /cancel` 仅操作已加载 manager（空闲已回收会话返回 404），浏览器断开 SSE 只释放订阅不触发取消。
- 原因：保证跨标签页和重启后共享一致会话目录，避免查列表触发批量对象初始化，并把页面断开与显式取消解耦。
- 排除：依赖浏览器本地缓存维护会话列表，或把 SSE 断连等同于主动取消任务。
