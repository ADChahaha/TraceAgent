# `test_task_flow.py`

这组测试覆盖 `backend` 第一版 FastAPI 主链路，使用 fake agent client 隔离真实 OCR 和抽取模型。

## 测试链路

```text
TestClient 上传 PDF
  -> 请求表单显式传入 task_type 和 task_spec
  -> backend 创建 SQLite 任务并让 POST /tasks 先返回 pending/uploaded
  -> 后台任务调用 fake agent 返回 document / extraction 结果
  -> fake agent trace 里带 source_selectors，backend replay 直接透传这张 path_id -> DOM id 映射
  -> task_service 对照 task_spec.fields 补齐 agent 没返回的字段占位
  -> backend 直接提交 resolved 字段，failed/None 占位字段保持未提交
  -> backend 保存 result、trace、audit 和失败原因
  -> GET /tasks/{task_id} 返回最终任务状态、失败原因、最终结果和审计记录
  -> GET /tasks/{task_id}/replay 从 document_processor stage response 组装展示 HTML，并在出口过滤页码、页眉、页脚版本号等旧任务文档 chrome
```

## 测试函数

- `test_failed_task_summary_returns_error_message`：验证 agent 抽取阶段返回 `failed` 时，`POST /tasks` 先返回 `pending/uploaded/error_message=null`，后台处理结束后 `GET /tasks/{task_id}` summary 会变成 `failed/done` 并带出 `error_message`，让前端能解释任务为什么失败。
- `test_create_task_returns_pending_before_background_pipeline_finishes`：验证创建接口不等待耗时 pipeline，响应体先返回 `pending/uploaded`；TestClient 中后台任务执行完后，summary 能查询到最终 `completed` 状态。
- `test_list_tasks_returns_latest_db_tasks_for_workspace`：验证 `GET /tasks` 会从 SQLite 返回最近更新的任务摘要列表，只包含任务状态、阶段和结果/trace 可用标记，不再包含字段路由或人工审核标记。
- `test_create_task_commits_resolved_agent_fields_without_routing`：验证 `POST /tasks` 先返回入队状态，后台 pipeline 会给标准化 block 补 `document_id/block_id`，并在抽取完成后直接把 resolved 字段提交为 agent 来源；summary、result 和 audit 都不再输出 route、reviewed、review_decision 或 review_value，同时 replay 会透传 `source_selectors` 供前端按原文 DOM id 定位。
- `test_create_task_accepts_multiple_files_and_merges_document_blocks`：验证 `POST /tasks` 支持重复 `files` 上传多个 PDF，并且先返回入队状态；后台会逐个调用 document processor，合并 markdown、md_list 和 blocks 后再执行字段抽取，并把所有 `document_id` 传入抽取 metadata；同时验证 `GET /trace` 只返回 document processor 和 file extraction agent 两段执行过程，字段 `process_steps` 固定为 `broad_extraction -> field_resolution -> final_result`。
- `test_missing_required_field_placeholder_stays_uncommitted_without_routing`：验证 file_extraction_agent 没有返回 task_spec 中的必填字段时，backend 会把该字段保存成 `failed/None` 占位；任务仍完成，字段不会提交最终值，也不会进入任何人工审核接口。
- `test_agent_process_without_tool_actions_keeps_resolution_step_completed`：验证字段没有额外 tool/action 时，`field_resolution` 步骤不能被标成 `skipped`，而是保留为已完成，说明 resolution 直接把候选证据定案为字段输出，并返回该阶段产出的字段名和值；同时验证 broad 阶段会把候选 block 正文写入 `evidence.blocks`。
- `test_create_task_rejects_unsupported_file_type`：验证上传非 PDF 文件时返回 `422`，不会进入 agent 调用链路。
- `test_capabilities_returns_supported_task_features_without_routing`：验证 `GET /capabilities` 返回文件类型、空任务类型列表、`external_task_spec` 和 `multiple_files` 能力开关，不再暴露 route 或 review 决策列表。
- `test_create_task_requires_external_task_spec`：验证调用方没有显式传入 `task_spec` 时返回 `422`，backend 不使用任何内置 task spec 兜底。
