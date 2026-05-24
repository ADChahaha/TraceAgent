# test_config.py

这份测试覆盖 backend QA-only 重构后的全局配置、路由挂载和数据库初始化。

实现链路：

```text
create_app(...)
  -> 挂载 /qa/tasks 系列 API
  -> 挂载 /healthz 健康检查 API
  -> 不再挂载旧 /tasks 字段抽取 API

initialize_database(connection)
  -> 删除旧 tasks / extracted_fields / field_traces / field_commits 等字段抽取 schema
  -> 如果已有旧 qa_tasks.memory_json 列，删除旧列并保留原有任务行
  -> 创建 qa_tasks / qa_documents / qa_messages / qa_turns / qa_events
```

## 测试函数

- `test_backend_settings_keeps_agent_service_configuration`：验证 backend 仍保留 agent service 地址、超时和 PDF/DOCX 能力配置。
- `test_backend_settings_loads_agent_cancel_timeout_from_env`：验证 `AGENT_SERVICE_CANCEL_TIMEOUT_SECONDS` 会覆盖后台 best-effort agent cancel 的短超时配置。
- `test_backend_registers_qa_routes_and_removes_old_task_routes`：验证应用只挂载 QA task API，旧 `/tasks` route 已下线。
- `test_backend_healthz_reports_ok`：验证 `/healthz` 返回 200 和 `{"status": "ok"}`，供本地启动和部署探活使用。
- `test_database_initialization_creates_qa_schema_and_drops_old_field_schema`：验证数据库初始化会创建 QA 会话表，并删除旧字段抽取/审核/提交表；同时确认 `qa_tasks` 不再包含 `memory_json`。
- `test_database_initialization_migrates_existing_qa_tasks_without_memory_json`：用带 `memory_json TEXT NOT NULL` 的旧 `qa_tasks` 表复现升级场景，验证初始化会删除旧列、保留旧任务行，并允许新的 memory-free `create_task(...)` 正常插入。
