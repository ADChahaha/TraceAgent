# Backend Devlog

last updated: 2026-04-29 20:32:22

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
