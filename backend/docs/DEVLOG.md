# Backend Devlog

last updated: 2026-05-20 20:43:54

## 2026-05-20 20:43:54

### 已完成工作

- `GET /tasks/{task_id}/replay` 的 `actions` 现在优先从 `trace.events` 生成，把非空 `model_message` 和 `tool_completed/tool_failed` 保留在同一条时间线里。
- 旧 trace 没有 `events` 时继续回退到 `trace.actions`，并保留剥掉旧 tool 顶层 `reason` 的兼容行为。
- 补充 backend replay 时间线回归测试和前端终态 replay 顺序回归测试，保证连续 tool group 仍折叠在原始位置，不集中挪到文字上方。

### 验证

- `PYTHONPATH=. uv run --project backend pytest backend/tests/test_task_flow.py`，结果 `14 passed`。
- `npm test -- --runInBand frontend/tests/task-detail.test.tsx`，结果 `37 passed`。

## 2026-05-18 18:37:31

### 已完成工作

- 新增 `task_events` 持久化事件表和 CRUD，任务内用递增 `sequence` 作为回放和续传游标。
- `POST /tasks`、`GET /tasks` 和 `GET /tasks/{task_id}` 现在返回 `stream.state` 与 `stream.last_event_seq`。
- 新增 `GET /tasks/{task_id}/events?after_seq=n`，以 SSE 返回 `seq > n` 的事件；任务未结束时会等待新事件，终态后关闭。
- 后台任务和人工复核会写入 `task.created`、阶段变化、文档处理、字段写入、route policy、review required 和终态事件。
- 同步更新 API/设计文档，并新增 `backend/tests/test_task_events.py` 与一一对应测试说明文档。

### 当前进展

- 后端已经具备第一阶段 `snapshot + events` 流式基础能力；agent 抽取仍可先走现有非流式调用，再把关键阶段归一成任务事件。

### 验证

- `PYTHONPATH=. pytest backend/tests -q`，结果 `22 passed`。

## 2026-05-05 01:05:20

### 已完成工作

- route policy 请求组装改为从 `table_extraction` action 中提取 `table_audit/query_audit`，只传 `quality_type/summary/table_id/query` 等事实摘要。
- backend 不再向 route_policy_agent 传递诊断 `status`，也不会把空白行样本、原始表格行或 cell 值塞进 `field_processes.diagnostics`。
- `table_audit` 没有现成 summary 时，backend 会从行列数、空白列分布和结构信号生成简短摘要。
- 同步更新 backend 设计/API 文档和测试说明，固定 `query_audit.summary` 会保留，而原始样本不会进入 route policy 请求。

### 当前进展

- 前端 replay 字段卡可使用 `query_audit.summary` 展示“查表摘要”，再用 `set_field.reason` 展示“模型判断”。

### 验证

- `python -m pytest backend/tests/test_task_flow.py -q`，结果 `15 passed`。
- `npm test -- task-detail.test.tsx --runInBand`，结果 `19 passed`。
- `npm run lint`，通过。

## 2026-05-04 22:37:01

### 已完成工作

- `AgentClient.evaluate_route_policy(...)` 删除 `policy_options` 参数，backend 不再向 route_policy_agent 发送 refs 裁剪配置。
- route_policy_agent 的 agent_stage_runs request 记录同步变为 `task_spec / field_outputs / refs_with_text / field_processes / metadata`。
- 同步更新 `backend/docs/API.md`，避免文档继续暗示 route policy request 带 `policy_options`。

### 当前进展

- backend 继续负责从抽取结果和 trace 组装完整 `refs_with_text`，route_policy_agent 负责完整消费这些最终证据文本。

### 验证

- `python -m pytest backend/tests/test_task_flow.py -q`，结果 `12 passed`。

## 2026-05-04 02:20:00

### 已完成工作

- 增加任务 replay 数据流：`GET /tasks/{task_id}/replay` 返回 documents、`display_html`、`outline_tree`、broad plan、actions、field states 和最终 result。
- backend 从 `agent_stage_runs` 中复用 document_processor 的 `display_html` 和 file_extraction_agent 的 trace，不重新解析 PDF 或重跑模型。
- route/replay validator 保留：最终 result 仍由 `set_field` actions reduce 得出，并校验证据 id 能在 document index 中定位。
- 修复 failed task 的 replay 可见性：即使 route_policy 阶段失败，只要 document_processor/file_extraction_agent 已完成，前端仍可打开 Review 动画检查抽取过程。
- route_policy 请求组装补齐 `refs_with_text[].refs[].text`，从保存的 `documents.blocks_json` 回填证据文本，避免下游 route 判断缺少 evidence 文本。
- 后端超时配置支持长 PDF OCR/抽取场景，前端代理也允许更大的上传 body。

### 当前进展

- 真实任务 `task_fc1c4d34a48742c9b7785f13f497ced8` 虽然最终状态为 `failed`，但 replay endpoint 已返回 `52` 个 actions、约 31 万字符 `display_html` 和完整字段结果。
- 这使得“route_policy 失败”和“file_extraction_agent 是否可信”可以分开检查，符合 Review 动画的调试需求。

### 验证

- `PYTHONPATH=. python -m pytest backend/tests/test_task_flow.py -q`
- `curl http://127.0.0.1:3010/api/backend/tasks/task_fc1c4d34a48742c9b7785f13f497ced8/replay` 验证 replay payload 包含 actions/display_html/outline_tree/result。

### 遇到的问题

- route_policy_agent 当前读取 `OPENAI_API_KEY`，而本地 `agent/.env` 使用 `API_KEY`，导致真实任务在 route_policy 阶段 422；本次没有调整 route prompt 或 route policy 配置。
- 旧详情页在 failed task 上会隐藏 replay，实际不利于查看已经成功的 extraction 输出，已改为只要有 trace/result 就尝试拉取 replay。

### 下一步

- 后续可单独修 route_policy_agent 的环境变量兼容，让它读取 `OPENAI_API_KEY or API_KEY`，并统一 route policy 模型名配置。

## 2026-04-30 20:42:20

### 已完成工作

- `services/route_policy.py` 从抽取 trace actions 组装 `field_processes`，传给 agent service 的 `route_policy_agent`。
- broad 阶段过程摘要会记录统一 `search_grep` 查询词、候选写入数量、`copy_field_candidates` 数量和 `finish_broad` 原因。
- resolution 阶段过程摘要会记录二次 `search_grep` 查询词、`add_resolution_candidate` 数量、`count_field_candidates` 统计结果和 `final_decision` 是否执行。
- backend 继续只保存 route policy 返回的 `field_routes` 并驱动 `accept / review / reject`，不在本地重做 LLM route 判断。
- 前端 trace 详情修复 action refs 渲染 key：用户界面仍只展示 document/page/span，不暴露 block_id，但 React key 会包含 block_id/index，避免同页同 span 的不同表格行触发重复 key warning。

### 当前进展

- 真实前端全流程任务 `task_ff50dfeab89a4923bdc4cbbd257c0a25` 已跑通：document processing、field extraction、route policy 三段均 completed，最终 `completed / done / accept`。
- route policy request 中可看到 `academic_paper_names` 的 broad 查询词和 count 摘要，`academic_paper_count` 的 route 原因会引用 `related_field_processes`。

### 验证

- `conda run -n agent-gate python -m pytest backend/tests/test_task_flow.py -q`，结果 `10 passed`。
- `pnpm test -- task-detail.test.tsx --runInBand`，结果 `7 passed`。

### 遇到的问题

- 前端 dev server 在真实长表格 trace 中提示 duplicate key，原因是 action refs 可能具有相同 document/page/span；已改为仅渲染 key 使用 block_id/index，展示文本不变。

## 2026-04-29 22:52:10

### 已完成工作

- 将 `POST /tasks` 调整为创建任务后立即返回 `pending / uploaded`，后台继续执行 document processing、field extraction 和 route policy。
- 后台 pipeline 失败时会把任务写成 `failed / done`，并通过 `GET /tasks/{task_id}` summary 的 `error_message` 暴露失败原因。
- 前端上传工作台不再预置 `task_type` 或业务字段；`task_spec` 默认只有空 `task_name` 和空 `fields`。
- 任务创建后右侧最近任务立即新增“处理中”记录，最新创建的任务固定显示在最上方；后续轮询只更新原位置的状态，完成后显示“处理结果”和 route / 失败状态。
- 同步更新 `backend/docs/API.md`、`backend/docs/DESIGN.md`、`frontend/docs/DESIGN.md` 和对应测试说明文档。

### 验证

- `PYTHONPATH=. pytest backend/tests -q`
- `pnpm test`
- `pnpm lint`

## 2026-04-29 20:32:22

### 已完成工作

- 同步根 `README.md`，将项目总览从早期服务拆分说明更新为当前毕业设计 MVP 闭环。
- 在 `backend/docs/DESIGN.md` 中补充 route 术语映射：`accept -> pass`、`review -> human_review`、`reject -> reject`，并说明第一版 MVP 暂不单独实现 `fallback`。
- 同步外部毕业设计文档的当前实现程度，把状态从 Agent PoC 更新为可运行 MVP 闭环，并标明剩余重点是实验、baseline、proxy review rule 和固定 demo 材料。

### 验证

- 本次只更新文档，不涉及运行时代码或测试文件。

## 2026-04-29 20:22:12

### 已完成工作

- 将前端复核页的字段证据文本改为默认收起的可折叠区域，标题显示 `证据文本（N）`，展开后继续按受控 markdown 渲染证据表格和正文。
- 保持 trace 页证据展示方式不变，只收敛 waiting_review 复核区的长证据文本占屏问题。
- 同步更新 `frontend/docs/DESIGN.md` 和 `frontend/tests/docs/task-detail.test.md`，说明复核证据折叠交互。

### 验证

- `pnpm test`
- `pnpm lint`
- `pnpm build`

## 2026-04-29 20:10:55

### 已完成工作

- 扩展字段级 `process_steps`，将 `final_result` 明确为 route policy 前的 agent 抽取结果，并新增 `route_validation` 步骤单独展示 route policy 的 `route / needs_review / route_reason`。
- `field_resolution` 现在展示 route 前 agent 输出字段、读取的相关字段和实际执行的 action，避免把 extraction 定案和 route validation 混在一起。
- 前端任务详情页同步展示 `Agent 输出字段（route 前）` 和 `Route 结论`，候选 blocks 继续以可折叠 markdown 正文展示且不暴露 block id。

### 验证

- `python -m pytest backend/tests -q`
- `pnpm test`
- `pnpm lint`
- `pnpm build`
- 使用 `agent/scripts` 文明寝室 task spec 和真实 PDF 在 `8004/3002` 验证：`civilized_dormitory_count` 的 agent 输出为 `14`，route policy 因证据可见 12 个文明寝室将字段路由到 `review`。

## 2026-04-29 18:45:33

### 已完成工作

- 扩展字段级 `agent_process`，新增 `process_steps`，按 `broad_extraction -> field_resolution -> final_result` 展示 broad 候选证据、resolution/tool 动作和最终结果。
- 让 `GET /trace`、review handoff 和 audit 中的字段决策过程复用同一套 `process_steps` 派生逻辑，不新增数据库表结构。
- 前端任务详情页在 trace、review 和 audit 中展示三段式 agent 过程，并保留原有证据 markdown 渲染。

### 验证

- `python -m pytest backend/tests -q`
- `pnpm test`
- `pnpm build`
- 临时 `8004/3002` 浏览器全流程验证：上传 DOCX、查看结果/证据/审计、人工复核 handoff 与提交后 audit。

## 2026-04-29 18:06:03

### 已完成工作

- 新增 `agent_stage_runs`，按顺序保存 `document_processor`、`file_extraction_agent`、`route_policy_agent` 的请求摘要、完整响应和 trace payload，并通过 `GET /tasks/{task_id}/trace.agent_trace` 返回给前端。
- 扩展 trace / review / audit 响应中的 `agent_process`，让前端能展示 file extraction 字段决策过程、证据、跨字段参考、global lookup 和 validation action。
- 新增 `frontend` Next.js + Tailwind + shadcn/ui 工作台，支持多文件上传、外部 `task_spec`、Markdown 证据渲染、人工复核、trace 和 audit 展示。
- 修复 review 后状态展示：任务完成后 `GET /tasks/{task_id}` 返回 `completed / done / needs_review=false`，前端刷新详情时同步更新最近任务缓存。

### 当前进展

- 已分开提交 backend 与 frontend 改动：`8375837 feat(backend): persist agent trace process`、`64a3dba feat(frontend): add Next.js workbench`。
- 当前本地服务使用 frontend `3000`、agent service `8002`、backend `8003`；前端代理已连到 backend。

### 遇到的问题

- 历史任务在新增 `agent_stage_runs` 之前创建，因此旧任务的 `agent_trace` 为空；新任务才会持久化完整 agent 调用记录。
- 复核完成后历史 route 仍可能是 `review`，所以 summary 的 `needs_review` 不能再从历史 `field_routes.needs_review` 推断，已改为只看当前任务状态。

### 验证

- `PYTHONPATH=. pytest backend/tests -q`
- `pnpm test`
- `pnpm lint`
- `pnpm build`

## 2026-04-28 16:09:24

### 已完成工作

- 移除 `backend` 内置 task spec，不再在 `core/config.py` 写死 `civilized_dormitory` 字段 schema。
- 调整 `POST /tasks`：调用方必须在 multipart 表单中显式传入 `task_spec` JSON，缺失时返回 `422`。
- 调整 `GET /capabilities`：不再暴露内置 `task_types`，改为通过 `features.external_task_spec=true` 声明由调用方提供 schema。
- 新增 `backend/tests/test_config.py` 及对应测试说明，验证配置层没有 `task_specs` 或 `task_specs_dir` 兜底。

### 当前进展

- 后端测试已通过：`PYTHONPATH=. pytest backend/tests -q`，共 6 个测试。
- `backend` 只负责接收和透传外部 task spec，不再决定业务字段定义。

### 下一步

- 在前端或实验脚本侧维护具体业务 task spec，并随 `POST /tasks` 一起提交。

## 2026-04-28 15:52:52

### 已完成工作

- 按当前设计实现 `backend` 第一版 FastAPI 服务，包含任务创建、状态查询、result、trace、review、audit 和 capabilities API。
- 新增 SQLite 初始化、CRUD 分层、agent HTTP client、route policy 请求组装、人工审核提交和字段级审计记录。
- 新增 `backend/tests/test_task_flow.py` 及对应测试说明，覆盖 accept 自动提交、review 人工修正、文件类型校验和 capabilities。
- 同步更新 `README.md`、`docs/API.md` 和 `docs/DESIGN.md`，明确第一版是同步处理模型，且上传原始文件不持久化。

### 当前进展

- 单元级后端测试已通过：`PYTHONPATH=. pytest backend/tests -q`。
- 已做真实 HTTP E2E：`backend` 调用运行中的 `agent/` 三个接口，完成 document processing、field extraction、route policy、review 提交和 audit 查询。
- E2E 中确认 trace 链路贯通：agent trace 会拆入 `field_traces`，review handoff 使用证据文本和 refs，audit 保存最终提交对应的 evidence refs。

### 遇到的问题

- 正向 E2E 样本中，`room_numbers` 字段定义为 `string`，但 agent 抽取结果返回数组 `["1-101", "1-102", "2-203"]`，route policy 因字段 schema 与输出格式不一致进入 `review`。
- 这不是 trace 断裂，而是字段类型契约需要收口：要么把字段定义改成列表型，要么让 extraction 输出稳定归一化为字符串。

### 下一步

- 固化真实 agent HTTP E2E 测试脚本，避免只依赖手工 curl 验证。
- 明确 `room_numbers` 的最终字段类型和序列化格式，再同步更新 task spec、抽取提示和 route policy 判断口径。

## 2026-04-28 10:56:45

### 已完成工作

- 修正后端文档存储边界：上传文件只作为调用 `document_processor` 的临时输入，数据库不保存原始文件、不保存 BLOB，只保存 markdown、md_list、blocks 和处理元信息。
- 将 route policy 口径从 backend 内部确定性规则调整为 agent service 提供的小 LLM + rules route 判断。
- 统一 route 类型为 `accept / review / reject`，并同步更新 API 示例、capabilities 和 DESIGN 中的字段 route 说明。

### 当前进展

- `backend` 仍只负责任务、SQLite 记录、状态流转、人工审核、最终结果和 audit。
- LLM 相关 route 判断移到 agent service，backend 只保存 route 输出并驱动 review / audit。

### 下一步

- 实现时先对接 agent 的 `document_processor`、`file_extraction_agent` 和 `route_policy_agent` 三个 HTTP 出口。
- 按当前文档口径设计 `documents` 表，只保存标准化文本结果和处理元信息。

## 2026-04-28 10:37:12

### 已完成工作

- 新增后端 API 设计文档，固定任务、结果、trace、review、audit 和 capabilities 接口。
- 新增后端 DESIGN 设计文档，明确 FastAPI、SQLite、agent HTTP 调用和数据库表设计。
- 补充 CRUD 分层设计，采用按业务聚合拆分，而不是每张表一个 CRUD 文件。

### 当前进展

- `backend` 处于设计文档阶段，API 边界、架构边界和数据库字段已经明确。

### 下一步

- 搭建 FastAPI 项目骨架。
- 按 TDD 实现 models、crud、services 和 routes。
