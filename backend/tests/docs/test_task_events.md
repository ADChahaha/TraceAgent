# `test_task_events.py`

这组测试覆盖后端流式事件 API 的第一阶段目标行为。事件流以 `task_events` 持久化记录为来源，`seq` 是任务内递增游标，前端可以用它做全量回放和断线续传。

## 测试链路

```text
TestClient 提交 POST /tasks
  -> backend 创建任务并写入 task.created 事件
  -> 后台 pipeline 写入阶段事件、字段事件和终态事件
  -> GET /tasks/{task_id} 返回 stream.state 和 stream.last_event_seq
  -> GET /tasks/{task_id}/events?after_seq=n 按 seq 回放持久化事件
```

## 测试函数

- `test_task_summary_includes_stream_cursor_after_pipeline_finishes`：验证任务跑完后，summary 仍返回 `stream.state=ended` 和最后一条事件序号，前端可以先读快照再决定是否续传事件。
- `test_task_events_endpoint_replays_persisted_events_and_respects_after_seq`：验证事件接口返回 `text/event-stream`，`after_seq=0` 会按顺序回放完整事件，`after_seq=n` 只补发 `seq > n` 的事件。
- `test_task_events_endpoint_waits_for_new_events_until_task_ends`：验证任务仍在运行时，事件接口会在补完历史事件后等待新事件，直到收到终态事件再结束响应。
- `test_submit_review_appends_terminal_task_event`：验证人工复核提交后会继续写入终态事件，前端可以从复核前的 `last_event_seq` 续传到 `task.completed`。
