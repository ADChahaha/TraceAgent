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

- `test_create_task_accept_route_commits_agent_fields`：验证 `POST /tasks` 在 route 为 `accept` 时会同步完成任务，给标准化 block 补 `document_id/block_id`，把字段结果提交为 agent 来源，并在 audit 中记录证据、lookup 使用、规则使用和字段级 agent 决策过程。
- `test_create_task_accepts_multiple_files_and_merges_document_blocks`：验证 `POST /tasks` 支持重复 `files` 上传多个 PDF/DOCX，backend 会逐个调用 document processor，合并 markdown、md_list 和 blocks 后再执行字段抽取，并把所有 `document_id` 传入抽取 metadata；同时验证 `GET /trace` 会返回 document processor、file extraction agent 和 route policy agent 三段执行过程，其中 extraction 步骤包含字段值、证据和 action 明细，并额外返回按调用顺序保存的 `agent_trace` 原始请求摘要、完整 agent 响应和 trace payload。
- `test_review_route_returns_handoff_and_accepts_revised_value`：验证 route 为 `review` 时任务进入 `waiting_review`，`GET /review` 返回证据、动作、route 原因和 agent 决策过程；提交 `revise_and_approve` 后任务 summary 必须变成 `completed/done` 且 `needs_review=false`，最终值改为人工来源并在审计记录中保留 agent 决策过程。
- `test_create_task_rejects_unsupported_file_type`：验证上传非 PDF/DOCX 文件时返回 `422`，不会进入 agent 调用链路。
- `test_capabilities_returns_supported_task_and_routes`：验证 `GET /capabilities` 返回文件类型、空任务类型列表、route 类型、review 决策、`external_task_spec` 和 `multiple_files` 能力开关。
- `test_create_task_requires_external_task_spec`：验证调用方没有显式传入 `task_spec` 时返回 `422`，backend 不使用任何内置 task spec 兜底。
