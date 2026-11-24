# 资源执行、两层串行与事务边界

返回 [SessionManager 架构](../SESSION_MANAGER.md)。

## 资源准备与读路径

```text
SessionRegistry.get_or_create -> 唯一 manager
  -> manager.upload_files / remove_file 以队列命令串行执行：
     队列内按最新状态校验累计配额 -> DocumentResourceClient.prepare_resources -> 事务替换资源引用

TurnRuntime.run（自治）
  -> begin 事务：建 turn 与用户消息、置 in_progress、认领 active_turn_id、按序读 chat_messages
  -> AgentClient.chat_completion(resources, messages, run_options)
  -> _on_event：校验 -> 配组 -> 配齐则事务写 chat_messages -> TurnView -> broadcast
  -> 终态/异常/流提前结束/取消 -> _finish 写终态事务并清 active_turn_id
```

- 上传、删除、替换均为队列命令，对同一会话严格串行；资源准备失败不改会话资源、不启轮次，调用方可重试。
- 下发 agent 的 `resource_path` 与 `resources.prepared` payload 只含 bundle 引用（`documents`/`index`）；`raw` 留在会话资源清单用于删除和限额校验。
- 只读通道不入命令队列：`download_file`（raw-only 经 ObjectStore 读回字节）、`list_documents`（解析 `documents.zip` 成员）、`read_document`（按整文件 key 取全文）与 `read_block`（段落回溯），bucket/key 均绑定本会话引用，跨会话不可达。
- gRPC 仅用 `PrepareResources` 与 `ChatCompletion`，取消用原 `call.cancel()`；`agent_completion_id` 只作关联，不用于重连远端执行。

## 串行化与事务边界

- manager 命令队列：`create`/`cancel`/`attach`/`detach`/`upload`/`remove`/`replace_resources` 编码为 `Command(name, args, reply)` 进入有界 FIFO 队列，`_run` 为唯一消费者。输入与文件形状校验在入口完成，依赖当前状态的配额校验在队列内执行，避免并发上传读改写竞争。队列满直接拒绝；调用方协程取消不撤销已入队命令，无人接收的订阅由 `_run` 回收。
- runtime 内部串行：单任务顺序处理事件并顺序 `await` 每次写，无需应用层写锁；每次写经 `asyncio.to_thread` 独占线程池线程与 thread-local 连接，跨连接写竞争由 SQLite 文件锁与 `busy_timeout` 排队。
- CRUD 与事务壳：service 统一调用 CRUD，不直写 SQL；CRUD 写函数本身不提交，由 `crud.transaction()` 统一执行 `BEGIN IMMEDIATE`、提交与异常回滚；提交成功后再更新 `TurnView` 与广播。

## 损坏出口与 Cancel 语义

- 写失败出口（`manager.fail()`）：标记损坏、清空 runtime 引用与缓存 `active_turn_id`（满足 idle 条件）、向挂起 `pending_cancel` 补发 `{"status": "failed"}` 并关闭清空订阅。
- 尽力收口与恢复：启动后台收口任务条件更新活跃轮为 `failed`/`storage_failure` 并清认领（由 `close()` 等待结束）；损坏 manager 拒绝除 `detach` 外命令，空闲后由 reaper 回收重载恢复，不做在线原地重建（投影异常同样停止 manager）。
- Cancel 语义：`_handle_cancel` 校验轮次后登记 `pending_cancel` 并调 `runtime.cancel()`；runtime 观察标志后自写 `cancelled` 终态并广播，manager 在广播终态时补发 cancel 响应；已终结轮次返回原终态。
- 不同 session 可并发，但当前以单 backend worker 运行，进程内唯一 manager 不解决多进程 owner 问题。
