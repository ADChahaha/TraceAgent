# `test_task_flow.py`

这组测试覆盖 `backend` 第一版 FastAPI 主链路，使用 fake agent client 隔离真实 OCR、抽取模型和 route policy 服务。

## 测试链路

```text
TestClient 上传 PDF / DOCX
  -> 请求表单显式传入 task_type 和 task_spec
  -> backend 创建 SQLite 任务
  -> fake agent 返回 document / extraction / route policy 结果
  -> backend 保存 result、trace、route、review 和 audit
  -> HTTP 接口返回任务状态、复核包、最终结果和审计记录
```

## 测试函数

- `test_create_task_accept_route_commits_agent_fields`：验证 `POST /tasks` 在 route 为 `accept` 时会同步完成任务，给标准化 block 补 `document_id/block_id`，把字段结果提交为 agent 来源，并在 audit 中记录证据和规则使用情况。
- `test_review_route_returns_handoff_and_accepts_revised_value`：验证 route 为 `review` 时任务进入 `waiting_review`，`GET /review` 返回证据、动作和 route 原因，提交 `revise_and_approve` 后最终值改为人工来源并写入审计记录。
- `test_create_task_rejects_unsupported_file_type`：验证上传非 PDF/DOCX 文件时返回 `422`，不会进入 agent 调用链路。
- `test_capabilities_returns_supported_task_and_routes`：验证 `GET /capabilities` 返回文件类型、空任务类型列表、route 类型、review 决策和 `external_task_spec` 能力开关。
- `test_create_task_requires_external_task_spec`：验证调用方没有显式传入 `task_spec` 时返回 `422`，backend 不使用任何内置 task spec 兜底。
