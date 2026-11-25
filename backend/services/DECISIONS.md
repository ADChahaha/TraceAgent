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

## 5. 轮次终态与取消以 `backend` 本地裁决为准，`agent` 取消仅作尽力清理

- 决定：`backend` 对所有轮次终态拥有唯一裁决与落库权，`agent` 输出的事件仅作候选输入由 `TurnRuntime` 校验状态、序号与工具组完整性后再经 `crud.transaction()` 提交（提交成功后才更新内存投影并广播 SSE）；取消时置本地 `cancel_requested = True` 并触发 gRPC `call.cancel()`，`TurnRuntime` 立即拦截迟到事件并在本地原子落库 `cancelled` 终态，远端 `call.cancel()` 仅作尽力资源清理，不以远端确认作为取消终态前提。
- 原因：网络延迟与模型推理特性使远端无法保证瞬时强同步停止，只有将唯一状态裁决与写入权收拢在 `backend`，才能防止取消后迟到事件污染新轮次或未提交即广播导致审计链断裂。
- 排除：等待远端 `agent` 返回 cancelled 确认后才落库终态的强同步取消协议；由 `agent` 判断轮次有效性；未提交数据库事务即向 SSE 广播稳定消息或终态。

## 6. 会话标题经 `AgentService.GenerateTitle` 异步生成并安全降级，关闭前排干线程写入

- 决定：首轮提交建立订阅后，`SessionManager` 在后台并发调用 `AgentService.GenerateTitle` 生成可读标题，经条件 `UPDATE`（仅标题为空时）落库并推送 `session.updated` 事件；模型报错、超时或未配置时静默降级为首条用户问题或首个文件名摘要，旧会话由查询与快照接口兜底派生（空会话回退 `Untitled workspace`），绝不展示 UUID；关闭 manager 取消标题任务时，若已进入线程池 SQLite 事务则等待线程退出后再释放连接。
- 原因：严守 `backend` 不做模型推理的分层边界，不阻塞首轮主问答 SSE 响应，同时避免异步写线程与数据库连接关闭竞态导致崩溃。
- 排除：在 `backend` 进程内直接调用 LLM SDK 生成标题；在首轮问答开始前同步等待标题生成；在会话列表中直接暴露 UUID。

## 7. 核心服务遵循依赖倒置原则（DIP），具体传输与对象存储仅在 `backend/main.py` 装配注入

- 决定：新增 [protocols.py](protocols.py) 声明 `DatabaseProtocol`、`CompletionStream`、`AgentGateway` 与 `DocumentGateway` 抽象协议；核心会话编排拆分为 `session_manager.py`、`session_resource_mixin.py`、`session_files.py`、`session_title_worker.py` 与 `session_catalog.py`（均 <= 300 行），仅依赖抽象协议与共享 `ObjectStore` 接口，禁止直接导入具体 `AgentClient`、`DocumentResourceClient` 或 `S3ObjectStore`/`build_s3_object_store`；具体实现统一由装配根 [backend/main.py](../main.py) 创建并注入，由 [check_architecture.py](../../scripts/check_architecture.py) 机械锁死。
- 原因：解耦核心并发编排与外部传输/存储细节，使测试与架构演进只需替换抽象实现，避免隐藏的局部具体构造破坏依赖方向。
- 排除：在 `SessionManager` 内部按需导入 `build_s3_object_store()` 或在业务模块直接绑定具体 gRPC client 类。
