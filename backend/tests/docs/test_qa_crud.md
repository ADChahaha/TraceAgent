# test_qa_crud.py

这份测试验证 `backend/crud/crud.py` 的读写与 `backend/models/schema.py` 完全对齐：每张表的插入、查询、更新都严格使用新表结构和列名，不再引用 `chat_documents`、`stage`、`metadata_json`、`user_message_id`、`chat_events.status/stage` 等旧结构。

## 实现链路

crud 是纯表读写封装，不做业务决策。测试通过真实 SQLite 初始化后的连接直接调用 crud 函数验证行为：

```text
connect_database(tmp_path / "crud.sqlite3")
  -> initialize_database(connection)  # 按 SCHEMA_SQL 建出五张 Chat 表
  -> chat_crud.create_session / create_turn / create_message / create_event / ...
  -> 断言返回 dict 的列集合恰好等于新 schema 列
```

关键约定：

- `chat_sessions` 只有 `id/status/active_turn_id/created_at/updated_at`，无 `stage`、`metadata_json`、`error_message`。
- `chat_turns` 只有 `id/session_id/status/agent_completion_id/created_at/updated_at/completed_at`，无 `user_message_id`、`error_message`。
- `chat_events` 只有 `id/session_id/turn_id/sequence/event_type/payload_json/created_at`，无 `status`、`stage`。
- `chat_messages` 必须带 `sequence/group_id/group_index/role/content/tool_calls_json/tool_call_id/name`；`tool_calls_json` 以 JSON 字符串传入。
- 文档产物写入 `chat_resources(id, session_id, type, location, created_at)`，`type` 区分 html/display_html/markdown 等产物，`UNIQUE(session_id, type, location)` 防重复。

## 测试函数

- `test_create_session_writes_only_schema_columns`：建任务后断言返回列恰为新 schema 五列，`get_session` 读回一致、缺失返回 `None`。
- `test_update_session_status_and_active_turn`：更新 `status` 与 `active_turn_id` 并刷新 `updated_at`。
- `test_update_session_clear_active_turn`：设置后再用 `clear_active_turn=True` 清空 `active_turn_id`。
- `test_list_sessions_orders_by_updated_at_desc`：多任务按 `updated_at DESC` 排序。
- `test_create_and_list_resource_columns`：写入两种 `chat_resources` 产物，断言列集合与 `list_resources` 顺序。
- `test_list_resources_filters_by_type`：按 `resource_type` 过滤资源列表。
- `test_resource_unique_per_session_type_location`：同 session 同 type 同 location 重复插入触发 `IntegrityError`。
- `test_create_and_list_message_columns`：写入 user 消息，断言列集合、默认 `tool_calls_json="[]"` 及 `list_messages` 读取。
- `test_list_messages_orders_by_sequence`：`list_messages` 按 `sequence ASC` 稳定排序。
- `test_create_tool_message_with_tool_call_fields`：assistant 带 `tool_calls_json`、tool 带 `tool_call_id/name` 的写入与读回。
- `test_create_turn_writes_only_schema_columns`：建 turn 断言列集合恰为新 schema 七列。
- `test_update_turn_status_and_completion_id`：更新 turn 状态、`agent_completion_id` 与 `completed_at`。
- `test_update_turn_status_if_current_conditional`：条件更新仅在 `status IN current_statuses` 时成功，否则返回 `None` 且不覆盖终态。
- `test_get_active_turn_finds_non_terminal_turn`：`get_active_turn` 只返回非终态 turn，忽略已 completed 的旧 turn。
- `test_create_event_assigns_sequence_and_columns`：事件按 session 递增分配 `sequence`，列集合为新 schema 七列，payload JSON 正确序列化。
- `test_list_events_after_sequence`：按 `sequence > after_sequence` 过滤事件。
- `test_get_last_event_sequence`：空任务返回 0，写入事件后返回当前最大序号。