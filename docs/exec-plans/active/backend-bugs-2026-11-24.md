# Backend 排查待修问题执行计划（2026-11-24）

来源：2026-11-24 会话排查，已逐条对照 `backend/` 与 `agent/` 源码核实。

## 目标与范围

- 做什么：按优先级逐项修复已核实的 9 个 `backend` 稳定性、协议兼容、并发互斥与性能问题，每项以可观察的外部行为验收测试或故障复现锁定结果。
- 不做什么：不改动 `backend` 单用户本地单进程部署模型，不引入外部队列或分布式锁，不自动迁移旧 `qa_*` 表。

## 验收标准与待修项

### 较严重问题

- [ ] 1. `BACKEND_DATABASE_PATH=":memory:"` 启动崩溃
  - 位置：[db.py](../../../backend/core/db.py)（L10-L39）、[main.py](../../../backend/main.py)（L26-L51）、[session_registry.py](../../../backend/services/session_registry.py)（L41-L54）
  - 原因：`lifespan` 在主线程执行 `initialize_database(database.connect())` 建表，随后 `registry.start()` 在 `asyncio.to_thread` 工作线程再次调用 `ThreadLocalDatabase.connect()`，每线程分别 `sqlite3.connect(Path(":memory:"))` 打开独立空内存库，导致 `no such table: chat_sessions`（[.github/workflows/ci.yml](../../../.github/workflows/ci.yml) L146 的 `deployment-smoke` 正使用了 `:memory:`）。
  - 验收：使用 `:memory:` 启动完整 `lifespan` 并跨工作线程读写 `chat_sessions` 不报缺表错误。

- [ ] 2. 真实 `agent` 失败工具在 `GET /resume` 刷新后被错判为 `"completed"`
  - 位置：[session_history.py](../../../backend/services/session_history.py)（L25-L37）、[turn_runtime.py](../../../backend/services/turn_runtime.py)（L194-L200）、[executor.py](../../../agent/service/file_extraction_agent/core/executor.py)（L44-L55）
  - 原因：`agent` 返回的失败工具载荷为 `{"ok": false, "errors": [...]}`，`_save_group` 直接写入 `chat_messages.content`；但 `_tool_detail` 仅检查 `"error" in parsed`，不认 `ok is False`。
  - 验收：使用真实 `agent` 失败工具载荷入库后调用 `GET /resume`，对应工具状态返回 `"failed"`。

- [ ] 3. 上传/删除未与活跃轮互斥，且同名覆盖误触发配额限制
  - 位置：[session_manager.py](../../../backend/services/session_manager.py)（L280-L305）
  - 原因：`_handle_upload` 和 `_handle_remove` 未检查 `self.active_turn_id`，回答期间调用 `prepare_resources` 会长时间占住 `_run()` 队列（阻塞同会话 `/cancel`、`/resume`、`detach`）并中途替换会话资源；`_handle_upload` 校验文件数和总字节数时未扣除同名替换的旧文件。
  - 验收：活跃轮期间上传/删除显式拒绝且不阻塞 `/cancel` 与 `/resume`；满配额时同名覆盖上传按差额计费并正常通过。

- [ ] 4. `POST /cancel` 存在误记 `"failed"` 和死锁路径
  - 位置：[turn_runtime.py](../../../backend/services/turn_runtime.py)（L56-L74）、[session_manager.py](../../../backend/services/session_manager.py)（L150-L152、L220-L232）
  - 原因：取消后若 gRPC 抛出普通异常，`TurnRuntime.run()` 的 `except Exception` 未判 `self.cancel_requested` 直接落为 `"failed"`；`_handle_cancel` 在 `_run()` 内 `await self.pending_cancel.reply`，当 `self.runtime is None` 或 `_finish()` 条件更新返回 `None` 未发终态广播时永久卡死；`broadcast()` 调 `set_result` 前未检查 `.done()`。
  - 验收：取消期间 gRPC 抛普通异常仍收口为 `"cancelled"`，且上述边界条件下 `POST /cancel` 在有限时间内返回而非悬挂。

### 异常收口、并发与性能问题

- [ ] 5. `fail()` 不可重入且损坏 manager 关闭时跳过 `_handle_stop`
  - 位置：[session_manager.py](../../../backend/services/session_manager.py)（L60-L92、L121-L138、L411-L427）
  - 原因：`TurnRuntime._begin()` 遇 `sqlite3.Error` 时 `fail()` 会被连续调用多次并覆盖 `self.recovery_task`，遗漏后台恢复任务；`_recover_active_turn()` 标 `"failed"` 时漏设 `completed_at`；`broken=True` 后 `close()` 发送的 `"stop"` 命令被 L121 拦截，导致 `_handle_stop()` 未执行且 `self.closed` 保持 `False`。
  - 验收：连续触发 `fail()` 仅保留单个收口任务且写齐 `completed_at`，损坏 manager 执行 `close()` 后 `closed` 置为 `True`。

- [ ] 6. `detach()` 在 `closing` 窗口或队列满时抛错，且 `_handle_detach` 重复定义
  - 位置：[session_manager.py](../../../backend/services/session_manager.py)（L99-L101、L247-L254、L403-L406）、[chat.py](../../../backend/routes/chat.py)（L76-L103）
  - 原因：`close()` 先置 `self.closing = True`，`_ask` 未放行 `"detach"`，此时 SSE 断开或异常清理会抛 `"会话管理器已关闭"`；队列满时死订阅残留；`_handle_detach` 在 L251 与 L403 重复定义。
  - 验收：`closing` 窗口与高负载下断开 SSE 不抛未处理异常、不泄漏死订阅，源码无重复 `_handle_detach`。

- [ ] 7. 每条流式 `delta` 都开 SQLite 写事务，且部分读路径在事件循环线程同步查库/解压
  - 位置：[turn_runtime.py](../../../backend/services/turn_runtime.py)（L140、L181-L187、L241-L248）、[session_manager.py](../../../backend/services/session_manager.py)（L221、L296、L342、L359）
  - 原因：`_on_event` 在 `ready is None`（`model_message.delta`、`tool_started`）时仍走 `_write()` 开事务并两次 `SELECT`；`_handle_cancel`、`_handle_remove`、`download_file` 在事件循环线程直接查库，`list_documents` 在事件循环线程同步解压 zip。
  - 验收：纯过程增量不开启 SQLite 写事务；读路径查库与 zip 解压不阻塞事件循环线程。

- [ ] 8. `GET /resume` 在轮次收尾写库窗口会丢 `current_turn`
  - 位置：[turn_runtime.py](../../../backend/services/turn_runtime.py)（L208-L215）、[session_manager.py](../../../backend/services/session_manager.py)（L242-L245）
  - 原因：`_finish()` 在 `await self._write(...)` 前就改写 `self.status`，但 `active_turn_id` 与 `self.runtime` 要等写库后 `broadcast()` 才清，窗口期内 `_handle_attach()` 会产出 `active_turn_id` 非空但 `current_turn=None` 的快照。
  - 验收：在 `_finish()` 写库窗口内调用 `GET /resume` 不出现 `active_turn_id` 非空但 `current_turn` 为空的断裂快照。

### 次要资源问题

- [ ] 9. 读通道每次新建 S3 客户端，上传读完整个请求体才判 413
  - 位置：[session_manager.py](../../../backend/services/session_manager.py)（L335-L338）、[chat.py](../../../backend/routes/chat.py)（L56-L62）
  - 原因：`main.py` 默认 `object_store=None`，每次 `_store()` 都新建 `boto3` 客户端；`_read_files()` 读完所有字节进内存后才检查 `upload_max_bytes`。
  - 验收：默认路径复用共享 `ObjectStore` 实例；超限上传在分块读取超阈值时提前中止返回 413。

## 进展与发现

- 2026-11-24：9 项问题均已在源码中核实定位，尚未开始修复；动手前按批次与用户确认具体边界取舍。

## Decision Log

（施工中用户拍板的取舍按三要素追加于此；全部完结移入 `docs/exec-plans/completed/` 前，每条须标明迁往的模块 `DECISIONS.md` / 回归测试或确认仅本次临时有效。）
