# `test_task_flow.py`

这组测试覆盖 `backend` 第一版 FastAPI 主链路，使用 fake agent client 隔离真实 OCR、抽取模型和 route policy 服务。

## 测试链路

```text
TestClient 上传 PDF / DOCX
  -> 请求表单显式传入 task_type 和 task_spec
  -> backend 创建 SQLite 任务并让 POST /tasks 先返回 pending/uploaded
  -> 后台任务调用 fake agent 返回 document / extraction / route policy 结果
  -> task_service 对照 task_spec.fields 补齐 agent 没返回的字段占位
  -> backend 从 trace actions 汇总 route policy 输入，包含表格工具观察摘要
  -> backend 保存 result、trace、route、review、audit 和失败原因
  -> GET /tasks/{task_id} 返回最终任务状态、失败原因、复核包、最终结果和审计记录
```

## 测试函数

- `test_failed_task_summary_returns_error_message`：验证 agent 抽取阶段返回 `failed` 时，`POST /tasks` 先返回 `pending/uploaded/error_message=null`，后台处理结束后 `GET /tasks/{task_id}` summary 会变成 `failed/done` 并带出 `error_message`，让前端能解释任务为什么失败。
- `test_route_policy_request_counts_broad_copy_candidates_in_broad_stage`：验证 backend 从 trace actions 组装 route policy `field_processes` 时，把 `copy_field_candidates` 计入 broad 候选写入数量，把 resolution 候选写入数量限定为 `add_resolution_candidate`，并只在 resolution 摘要里保留 `count_field_candidates` 的字段名和数量。
- `test_route_policy_request_summarizes_tool_name_actions`：验证新版工具 trace 只有 `tool_name/args` 时，backend 仍能把 `table_extraction` 的 SQL 汇总为 broad 查询信号，把 `set_field` 识别为最终定案，并把写入 reason 放到 resolution 摘要里。
- `test_route_policy_request_preserves_table_and_query_audit_summaries`：验证 `table_extraction` action result 中的 `table_audit/query_audit` 会被汇总到 `field_processes` 的 diagnostics 摘要里，只保留 summary/table_id/query 等事实观察，不携带 status、表格原始行或 cell 内容。
- `test_route_policy_request_preserves_query_audit_summary_without_raw_samples`：验证稀疏标签列的 `query_audit.summary` 会进入 route policy 请求，空白行样本和原始表格值不会进入。
- `test_route_policy_request_backfills_ref_text_from_document_blocks`：验证 route policy 请求组装 refs 时，如果 trace evidence 缺少 texts，会从已保存的 document blocks 回填证据文本、document_id 和 page。
- `test_create_task_returns_pending_before_background_pipeline_finishes`：验证创建接口不等待耗时 pipeline，响应体先返回 `pending/uploaded`；TestClient 中后台任务执行完后，summary 能查询到最终 `completed` 状态。
- `test_create_task_accept_route_commits_agent_fields`：验证 `POST /tasks` 在 route 为 `accept` 时先返回入队状态，后台 pipeline 会给标准化 block 补 `document_id/block_id`，把字段结果提交为 agent 来源，并在 audit 中记录证据、action_types 和字段级 agent 决策过程；`result` 只承载字段值，证据和 actions 留在 `trace`；route policy request 额外带 `field_processes`，只包含 broad / resolution 的统一 search 查询词、候选写入数量、count 摘要、结束原因和 final_decision 状态，不带工具返回结果。
- `test_create_task_accepts_multiple_files_and_merges_document_blocks`：验证 `POST /tasks` 支持重复 `files` 上传多个 PDF/DOCX，并且先返回入队状态；后台会逐个调用 document processor，合并 markdown、md_list 和 blocks 后再执行字段抽取，并把所有 `document_id` 传入抽取 metadata；同时验证 `GET /trace` 会返回 document processor、file extraction agent 和 route policy agent 三段执行过程，其中 extraction 字段决策必须包含 `process_steps`，按 `broad_extraction -> field_resolution -> final_result -> route_validation` 展示 broad 候选 block 正文、search_grep/add_broad_candidate/finish_broad、route 前 final_decision 输出、route policy 验证结论和最终 route 原因；route policy 的 `agent_trace.request.field_processes` 只保留 search 查询词，不暴露 refs 或 block 结果；并额外返回按调用顺序保存的 `agent_trace` 原始请求摘要、完整 agent 响应和 trace payload。
- `test_review_route_returns_handoff_and_accepts_revised_value`：验证 route 为 `review` 时 `POST /tasks` 先返回入队状态，后台处理后任务进入 `waiting_review`，`GET /review` 返回证据、动作、route 原因和 agent 决策过程；字段过程会把 agent 抽取结果和 route validation 分开展示，提交 `revise_and_approve` 后任务 summary 必须变成 `completed/done` 且 `needs_review=false`，最终值改为人工来源并在审计记录中保留 agent 决策过程。
- `test_review_handoff_includes_missing_required_field_placeholder`：验证 file_extraction_agent 没有返回 task_spec 中的必填字段时，backend 会把该字段保存成 `failed/None` 占位；route policy 判定 review 后，`GET /review` 仍能返回字段显示名、空 agent_value、失败状态和 route 原因，人工补录提交后最终值来自 human。
- `test_agent_process_without_tool_actions_keeps_resolution_step_completed`：验证字段没有额外 tool/action 时，`field_resolution` 步骤不能被标成 `skipped`，而是保留为已完成，说明 resolution 直接把候选证据定案为字段输出，并返回该阶段产出的字段名和值；同时验证 broad 阶段会把候选 block 正文写入 `evidence.blocks`。
- `test_create_task_rejects_unsupported_file_type`：验证上传非 PDF/DOCX 文件时返回 `422`，不会进入 agent 调用链路。
- `test_capabilities_returns_supported_task_and_routes`：验证 `GET /capabilities` 返回文件类型、空任务类型列表、route 类型、review 决策、`external_task_spec` 和 `multiple_files` 能力开关。
- `test_create_task_requires_external_task_spec`：验证调用方没有显式传入 `task_spec` 时返回 `422`，backend 不使用任何内置 task spec 兜底。
