# test_config.py

这份测试覆盖 backend 的全局配置、路由挂载和数据库初始化。核心变更后，agent 地址改为 gRPC target；`initialize_database` 只负责建当前 Chat schema，不再清理或迁移旧表。

## 实现链路

```text
BackendSettings.from_env() / BackendSettings(...)
  -> 读取 database_path、agent_service_target、请求/取消超时、gRPC 消息上限、supported_file_types

create_app(settings=...)
  -> 挂载 /chat/completion、/resume、/cancel 与 /healthz
  -> 不再挂载旧 /tasks 字段抽取 API

initialize_database(connection)
  -> PRAGMA journal_mode = WAL
  -> 逐条执行 SCHEMA_SQL，创建 chat_sessions / chat_resources / chat_messages / chat_turns / chat_events
  -> 不删旧表、不做 memory_json 迁移；旧库按“直接重建新库”处理
```

## 测试函数

- `test_backend_settings_keeps_agent_service_configuration`：验证默认 `agent_service_target == "127.0.0.1:8001"`、请求超时 1200s、取消超时 2s、gRPC 消息上限 64 MiB、支持 pdf/docx。
- `test_backend_settings_loads_agent_target_from_env`：验证 `AGENT_SERVICE_TARGET` 会覆盖默认 gRPC target。
- `test_backend_settings_loads_agent_grpc_message_limit_from_env`：验证 `AGENT_GRPC_MAX_MESSAGE_BYTES` 会覆盖默认 gRPC 消息上限。
- `test_backend_settings_loads_agent_cancel_timeout_from_env`：验证 `AGENT_SERVICE_CANCEL_TIMEOUT_SECONDS` 会覆盖后台 best-effort agent cancel 的短超时。
- `test_backend_registers_chat_completion_resume_cancel`：验证挂载三个会话执行接口，旧 `/tasks` 与 `/qa/tasks` 下线。因为 FastAPI 0.141 的 `include_router` 会生成 `_IncludedRouter`，测试用 `_route_paths` 递归展开 `path`、`routes` 和 `original_router.routes` 收集路径。
- `test_backend_healthz_reports_ok`：验证 `/healthz` 返回 200 和 `{"status": "ok"}`。
- `test_database_initialization_creates_chat_schema_without_migrating_legacy_tables`：先在内存库建旧 `tasks`/`extracted_fields` 表，再初始化；断言五张 Chat 表建出、`chat_sessions` 恰为新 schema 五列，且旧表仍保留（确认初始化不再清理或迁移旧库）。
