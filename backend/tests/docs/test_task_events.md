# `test_task_events.py`

这组测试覆盖后端流式事件 API 的第一阶段目标行为。事件流以 `task_events` 持久化记录为来源，`seq` 是任务内递增游标，前端可以用它做全量回放和断线续传。

## 测试链路

```text
TestClient 提交 POST /tasks
  -> backend 创建任务并写入 task.created 事件
  -> TaskService / AuditService 通过 ThreadLocalDatabase 按当前线程取得 SQLite connection
  -> 后台 pipeline 和前端轮询线程不会复用同一个 sqlite3.Connection 对象
  -> 后台 pipeline 写入阶段事件，并消费 file_extraction_agent NDJSON stream
  -> backend 把 agent 工具事件归一成 task_events，最后用 result_completed 收口
  -> GET /tasks/{task_id} 返回 stream.state 和 stream.last_event_seq
  -> GET /tasks/{task_id}/events?after_seq=n 按 seq 回放持久化事件
```

## 测试函数

- `test_task_summary_includes_stream_cursor_after_pipeline_finishes`：验证任务跑完后，summary 仍返回 `stream.state=ended` 和最后一条事件序号，前端可以先读快照再决定是否续传事件。
- `test_task_events_endpoint_replays_persisted_events_and_respects_after_seq`：验证事件接口返回 `text/event-stream`，`after_seq=0` 会按顺序回放完整事件，`after_seq=n` 只补发 `seq > n` 的事件。
- `test_backend_uses_thread_local_sqlite_connections_for_concurrent_polling`：验证 backend service 在不同 worker thread 中取得的是不同 SQLite connection，避免后台写事件和前端轮询列表/事件时并发使用同一个 connection 造成 `bad parameter`、`tuple index out of range` 或误报 `task not found`。
- `test_task_events_endpoint_waits_for_new_events_until_task_ends`：验证任务仍在运行时，事件接口会在补完历史事件后等待新事件，直到收到终态事件再结束响应。
- `test_removed_manual_check_endpoint_is_not_available_and_does_not_append_events`：验证旧人工检查入口不可用，调用后不会追加新事件；完整事件流最终停在 `task.completed`，payload 不再带 route 信息。
- `test_backend_consumes_file_extraction_stream_and_persists_agent_events`：验证 backend 会消费 file_extraction_agent 的 stream 入口，把 tool/field 过程事件写入 `task_events`，转发时剥掉 tool 顶层 `reason`，并仍由 `result_completed` 收口到最终任务结果。
