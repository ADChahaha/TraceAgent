# Backend Design

这份文档是 `backend` 服务的设计入口，面向毕业设计原型阶段。接口细节见 [API.md](API.md)。

## 1. 目标与边界

`backend` 负责把 `agent service` 产出的抽取结果变成可治理、可审核、可追责的业务任务。它不重新实现 OCR 或字段抽取，而是围绕上传文件、任务状态、route policy、人工审核、最终结果和审计记录组织流程。

核心链路是：

```text
前端或脚本上传 PDF / DOCX
  -> backend 创建任务记录
  -> backend 通过 HTTP 调用 document_processor，把上传文件转成 markdown + blocks
  -> backend 保存标准化文本结果，不保存原始文件
  -> backend 通过 HTTP 调用 file_extraction_agent
  -> agent service 返回 ExtractionResult(result + trace)
  -> backend 组装 field_outputs + refs_with_text 并调用 route_policy_agent
  -> agent service 返回 accept / review / reject 字段路由
  -> accept 自动生成字段提交记录
  -> review 等待人工审核
  -> review 提交后更新最终结果和 audit
```

职责边界：

- `backend` 管理任务、文档标准化结果、数据库记录、route 输出、人工审核和 audit。
- `agent service` 负责 `document_processor`、`file_extraction_agent` 和 `route_policy_agent`，返回标准化结果、字段结果、trace 和字段路由。
- `backend` 通过 HTTP 调用 `agent service`，不直接 import `agent/` 内部包。
- `backend` 不持久化用户上传的原始文件；上传文件只在请求处理过程中用于调用 `document_processor`。
- `agent service` 不直接访问 `backend` 的 SQLite 数据库。
- 第一版不做登录、权限、多用户、批量任务、取消任务和重试任务。

## 2. FastAPI 项目结构

推荐结构如下：

```text
backend/
  main.py
  core/
    config.py
    db.py
  routes/
    tasks.py
    reviews.py
    capabilities.py
  schemas/
    tasks.py
    reviews.py
    results.py
  crud/
    tasks.py
    extraction.py
    reviews.py
    audit.py
  services/
    task_service.py
    agent_client.py
    route_policy.py
    review_service.py
    audit_service.py
  models/
    task.py
    document.py
    extraction.py
    review.py
    audit.py
  docs/
    API.md
    DESIGN.md
```

模块边界：

- `main.py` 创建 FastAPI app，挂载 `routes/`，不写业务流程。
- `core/config.py` 管理数据库路径、agent service 地址等配置。
- `core/db.py` 初始化 SQLite 连接和 session，不直接写业务查询。
- `routes/` 只做 HTTP 入参出参适配，把请求转交给 `services/`。
- `schemas/` 定义 FastAPI 请求和响应模型，不直接定义数据库表。
- `models/` 定义 SQLite 表结构和 ORM 模型。
- `crud/` 封装基础数据库读写，不写业务编排。
- `services/` 负责任务创建、agent 调用、状态流转、route policy、review 和 audit。

## 3. 主处理链路

任务创建后的处理流程如下：

```text
POST /tasks 上传文件
  -> routes.tasks 接收 UploadFile、task_type、task_spec、metadata
  -> task_service 校验文件类型和任务类型
  -> task_service 读取上传文件 bytes，计算 size_bytes 和 sha256
  -> SQLite 写入 tasks
  -> task_service 将任务置为 processing / document_processing
  -> agent_client 用上传文件 bytes 通过 HTTP 调用 agent service 的文档处理接口
  -> SQLite 写入 documents(markdown / md_list_json / blocks_json / meta_info_json / warnings_json)
  -> agent_client 再通过 HTTP 调用 agent service 的字段抽取接口
  -> SQLite 写入 agent_runs / extracted_fields / field_traces
  -> route_policy 从字段结果和 trace refs 组装 field_outputs + refs_with_text
  -> agent_client 通过 HTTP 调用 agent service 的 route policy 接口
  -> SQLite 写入 field_routes
  -> 如果全部字段可 accept，写入 field_commits 并将任务置为 completed / done
  -> 如果存在 review 字段，将任务置为 waiting_review / review
  -> 如果 route=reject，将任务置为 rejected / done
  -> 如果 agent 或流程失败，将任务置为 failed、review 或 reject
```

人工审核流程如下：

```text
GET /tasks/{task_id}/review
  -> review_service 读取 extracted_fields、field_traces、field_routes
  -> 组装 handoff 包，返回字段值、证据、定位、route 原因和 actions

POST /tasks/{task_id}/review
  -> review_service 校验任务状态必须是 waiting_review
  -> 写入 reviews / review_fields
  -> approve 沿用 agent_value 作为 final_value
  -> revise_and_approve 使用 review_value 作为 final_value
  -> reject 将任务置为 rejected，不生成对应字段提交
  -> audit_service 写入 field_commits
  -> 更新 tasks.status / stage / completed_at
```

## 4. 模块职责

### `routes.tasks`

暴露任务相关 API：

- `POST /tasks`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/result`
- `GET /tasks/{task_id}/trace`
- `GET /tasks/{task_id}/audit`

处理步骤：

```text
HTTP 请求
  -> Pydantic schema 解析
  -> 调用 task_service / audit_service
  -> 将服务层对象映射成 API 响应
```

### `routes.reviews`

暴露人工审核 API：

- `GET /tasks/{task_id}/review`
- `POST /tasks/{task_id}/review`

它只负责协议适配，不直接判断字段是否可通过。

### `routes.capabilities`

暴露 `GET /capabilities`，返回支持文件类型、任务类型、route 类型、review 决策类型和 feature flags。

### `crud`

`crud/` 只负责最基础的数据库读写，也就是创建、查询、更新和删除记录。它不决定业务流程，不调用 agent service，也不执行 route policy。

数据库访问链路应当保持为：

```text
routes
  -> services
  -> crud
  -> models / SQLite
```

不要让 `routes/` 直接操作 `models/`，也不要把复杂业务流程塞进 `crud/`。例如“什么时候调用 agent、什么时候进入人工审核、什么时候生成 audit”属于 `services/`；“把 task 状态更新成 waiting_review”或“按 task_id 查询 field_routes”才属于 `crud/`。

第一版不按每张表机械拆文件，而是按业务聚合拆：

```text
crud/tasks.py
  -> tasks
  -> documents

crud/extraction.py
  -> agent_runs
  -> extracted_fields
  -> field_traces
  -> field_routes

crud/reviews.py
  -> reviews
  -> review_fields

crud/audit.py
  -> field_commits
```

这样拆分的原因是这些表通常按同一个业务动作一起读写：

```text
创建任务
  -> 同时写 tasks 和 documents

保存 agent 输出
  -> 同时写 agent_runs、extracted_fields、field_traces

执行 route policy
  -> 读取 extracted_fields / field_traces
  -> 写 field_routes

提交人工审核
  -> 写 reviews / review_fields
  -> 更新 extracted_fields.final_value_json

生成审计记录
  -> 写 field_commits
```

也就是说，CRUD 的拆分标准不是“每个 table 一个文件”，而是“哪些表经常在同一个业务动作里一起使用”。

### `services.task_service`

负责任务创建和状态流转：

```text
UploadFile + task_type + metadata
  -> 读取文件 bytes
  -> 创建 task
  -> 调用 agent_client 生成 document_processor 结果
  -> 保存 document markdown / blocks
  -> 调用 agent_client 执行字段抽取
  -> 保存 agent 输出
  -> 调用 route_policy 组装请求并调用 agent route_policy_agent
  -> 更新任务状态
```

### `services.agent_client`

只通过 HTTP 调用 `agent service`：

```text
upload file bytes + filename + file_type
  -> POST /v1/document-processor/process
  -> ProcessResult
  -> backend 为 blocks 补 document_id / block_id
  -> POST /v1/file-extraction-agent/extract
  -> ExtractionResult(result + trace)
  -> POST /v1/route-policy-agent/evaluate
  -> RoutePolicyResult(field_routes)
```

约束：

- 不直接 import `document_processor` 或 `file_extraction_agent`。
- 不直接写数据库。
- 只返回调用结果或抛出可被 `task_service` 捕获的异常。

### `services.route_policy`

负责把 backend 已保存的字段结果和 trace refs 转成 agent route policy 需要的请求。它不在 backend 内执行 LLM route 判断，也不重新抽取字段值。

```text
extracted_fields + field_traces + task_spec
  -> 从 trace refs 和证据文本组装 refs_with_text
  -> 从 extracted_fields 组装 field_outputs
  -> 调用 agent /v1/route-policy-agent/evaluate
  -> 保存 RoutePolicyResult.field_routes
```

### `services.review_service`

负责人工审核包和审核提交：

- `GET review`：把 agent 字段结果、trace 和 route 原因合并成 handoff 包。
- `POST review`：保存人工决策，并把 `review_value` 合并到最终字段结果。

### `services.audit_service`

负责字段级提交记录：

```text
final field value + route + review decision + trace refs
  -> 提取 evidence_refs、related_fields、lookup / validation 标记
  -> 写入 field_commits
```

## 5. 数据库表设计

第一版使用 SQLite 本地数据库。字段类型在设计上采用逻辑类型；JSON 内容以 SQLite `TEXT` 保存，序列化为 JSON 字符串。

### `documents`

保存上传文件的元信息和 `document_processor` 的标准化结果。毕业设计原型阶段不保存用户上传的原始文件内容；数据库只保存用于抽取、展示和 trace 的 markdown、blocks 和处理元信息。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 文档 ID |
| `task_id` | `TEXT INDEX` | 所属任务 ID |
| `filename` | `TEXT` | 原始文件名 |
| `file_type` | `TEXT` | `pdf` 或 `docx` |
| `content_type` | `TEXT` | 上传时的 MIME 类型 |
| `upload_size_bytes` | `INTEGER` | 上传文件大小，仅作元信息 |
| `upload_sha256` | `TEXT` | 上传文件内容哈希，仅作去重或排查元信息 |
| `markdown` | `TEXT` | `document_processor` 输出的整篇 Markdown |
| `md_list_json` | `TEXT` | `document_processor` 输出的 `md_list` |
| `blocks_json` | `TEXT` | 标准化 blocks，后续抽取和证据定位使用 |
| `processor_meta_json` | `TEXT` | 文档处理阶段的 `meta_info` |
| `warnings_json` | `TEXT` | 文档处理阶段的 warnings |
| `processed_at` | `DATETIME NULL` | 文档标准化完成时间 |
| `created_at` | `DATETIME` | 创建时间 |

### `tasks`

保存任务级状态、阶段和 route 摘要。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 任务 ID |
| `task_type` | `TEXT` | 任务类型，例如 `civilized_dormitory` |
| `status` | `TEXT` | `pending / processing / waiting_review / completed / rejected / failed` |
| `stage` | `TEXT` | `uploaded / document_processing / extraction / route_policy / review / field_commit / done` |
| `route` | `TEXT NULL` | 顶层 route 摘要 |
| `route_reason` | `TEXT NULL` | 顶层 route 原因 |
| `metadata_json` | `TEXT` | 调用方传入的元信息 |
| `error_message` | `TEXT NULL` | 失败原因 |
| `created_at` | `DATETIME` | 创建时间 |
| `updated_at` | `DATETIME` | 更新时间 |
| `completed_at` | `DATETIME NULL` | 完成时间 |

### `agent_runs`

保存一次 agent 执行的输入、输出和运行状态。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | agent run ID |
| `task_id` | `TEXT INDEX` | 所属任务 ID |
| `agent_status` | `TEXT` | agent 返回的 `completed / failed` |
| `failure_reason` | `TEXT NULL` | agent 失败原因 |
| `request_json` | `TEXT` | 传给 agent 的主要请求摘要 |
| `result_json` | `TEXT` | `ExtractionResult.result` |
| `trace_json` | `TEXT` | `ExtractionResult.trace` |
| `started_at` | `DATETIME` | agent 调用开始时间 |
| `finished_at` | `DATETIME NULL` | agent 调用结束时间 |

### `extracted_fields`

保存字段级 agent 原始结果和后端最终值。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 记录 ID |
| `task_id` | `TEXT INDEX` | 所属任务 ID |
| `field_name` | `TEXT` | 字段名 |
| `display_name` | `TEXT` | 展示名 |
| `field_type` | `TEXT` | 字段类型 |
| `agent_status` | `TEXT` | agent 字段状态 |
| `agent_value_json` | `TEXT NULL` | agent 原始值 |
| `final_value_json` | `TEXT NULL` | 后端治理后的最终值 |
| `source` | `TEXT` | `agent / human / none` |
| `reason` | `TEXT NULL` | 定案原因 |
| `failure_reason` | `TEXT NULL` | 字段失败原因 |
| `created_at` | `DATETIME` | 创建时间 |
| `updated_at` | `DATETIME` | 更新时间 |

### `field_traces`

保存字段级证据、动作和解释信息。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 记录 ID |
| `task_id` | `TEXT INDEX` | 所属任务 ID |
| `field_name` | `TEXT` | 字段名 |
| `evidence_json` | `TEXT` | 证据文本和 refs |
| `related_fields_json` | `TEXT` | 相关字段列表 |
| `actions_json` | `TEXT` | `field_reference / global_lookup / validation_rule / model_call_error` 等动作 |
| `trace_status` | `TEXT` | trace 字段状态 |
| `reason` | `TEXT NULL` | 成功定案原因 |
| `failure_reason` | `TEXT NULL` | 失败原因 |

### `field_routes`

保存 route policy 对每个字段的判断。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 记录 ID |
| `task_id` | `TEXT INDEX` | 所属任务 ID |
| `field_name` | `TEXT` | 字段名 |
| `route` | `TEXT` | `accept / review / reject` |
| `route_reason` | `TEXT` | route 原因 |
| `needs_review` | `BOOLEAN` | 是否需要人工审核 |
| `created_at` | `DATETIME` | 创建时间 |

### `reviews`

保存一次人工审核提交。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | review ID |
| `task_id` | `TEXT INDEX` | 所属任务 ID |
| `decision` | `TEXT` | `approve / revise_and_approve / reject` |
| `comment` | `TEXT NULL` | 人工备注 |
| `reviewer` | `TEXT NULL` | 审核者；原型阶段可为空或固定为 `human` |
| `created_at` | `DATETIME` | 创建时间 |

### `review_fields`

保存人工审核对字段的处理结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 记录 ID |
| `review_id` | `TEXT INDEX` | 所属 review ID |
| `task_id` | `TEXT INDEX` | 所属任务 ID |
| `field_name` | `TEXT` | 字段名 |
| `agent_value_json` | `TEXT NULL` | agent 原始值 |
| `review_value_json` | `TEXT NULL` | 人工修正值 |
| `final_value_json` | `TEXT NULL` | 人工审核后的最终值 |
| `decision` | `TEXT` | 字段级审核结论 |
| `comment` | `TEXT NULL` | 字段级备注 |

### `field_commits`

保存字段级提交与责任链路，用于 `GET /tasks/{task_id}/audit`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | 提交记录 ID |
| `task_id` | `TEXT INDEX` | 所属任务 ID |
| `field_name` | `TEXT` | 字段名 |
| `final_value_json` | `TEXT NULL` | 最终提交值 |
| `route` | `TEXT` | 字段 route |
| `reviewed` | `BOOLEAN` | 是否经过人工审核 |
| `review_decision` | `TEXT NULL` | 人工审核结论 |
| `agent_value_json` | `TEXT NULL` | agent 原始值 |
| `review_value_json` | `TEXT NULL` | 人工修正值 |
| `evidence_refs_json` | `TEXT` | 最终字段证据定位 |
| `used_global_lookup` | `BOOLEAN` | 是否使用过全局补查 |
| `used_validation_rule` | `BOOLEAN` | 是否使用过 validation rule |
| `related_fields_json` | `TEXT` | 定案参考字段 |
| `committed_by` | `TEXT` | `agent / human` |
| `committed_at` | `DATETIME` | 提交时间 |

## 6. 状态流转

任务状态流转如下：

```text
pending
  -> processing
  -> completed
```

人工审核分支：

```text
pending
  -> processing
  -> waiting_review
  -> completed
```

拒绝分支：

```text
pending
  -> processing
  -> waiting_review
  -> rejected
```

失败分支：

```text
pending
  -> processing
  -> failed
```

阶段 `stage` 比 `status` 更细，用于前端展示当前进度：

```text
uploaded
  -> document_processing
  -> extraction
  -> route_policy
  -> review
  -> field_commit
  -> done
```

## 7. Route Policy 规则

第一版 route policy 由 agent service 的 `route_policy_agent` 执行。backend 不直接判断字段是否 `accept / review / reject`，只负责准备输入、保存输出和驱动后续状态。

route policy 的输出只有三类：

```text
accept
  -> 结果可信，可以自动进入字段提交记录

review
  -> 结果可能可用，但需要人工检查或修改后再通过

reject
  -> 关键字段不可用，或 refs 文本不足以支持字段值，不允许进入最终提交
```

执行流程：

```text
task_spec + extracted_fields + field_traces
  -> backend 组装 field_outputs
  -> backend 从 refs 和证据文本组装 refs_with_text
  -> agent route_policy_agent 校验输入完整性
  -> agent route_policy_agent 只根据字段输出和 refs 文本判断 route
  -> backend 写入 field_routes(route, route_reason, needs_review)
```

`route_policy.py` 的输出必须落库到 `field_routes`，不能只保存在内存里。这样 `GET /tasks/{task_id}/review` 和 `GET /tasks/{task_id}/audit` 都能解释字段为什么进入某条路径。

## 8. Human Review 流程

人工审核输入不是一组孤立字段，而是 handoff 包：

```text
extracted_fields
  -> field_traces
  -> field_routes
  -> review_service 组装
  -> 字段值 + 证据文本 + 证据位置 + route 原因 + actions
```

人工审核支持三类结论：

- `approve`：接受 agent 结果，`final_value_json = agent_value_json`。
- `revise_and_approve`：接受人工修正，`final_value_json = review_value_json`。
- `reject`：拒绝该任务或字段，不生成对应字段提交。

人工审核提交后：

```text
review payload
  -> 写入 reviews / review_fields
  -> 更新 extracted_fields.final_value_json 和 source
  -> audit_service 生成 field_commits
  -> 更新 tasks.status / stage / completed_at
```

## 9. Result / Trace / Audit 边界

三类数据必须分开保存和返回：

- `result`：面向业务展示和写库，保存最终字段结果。
- `trace`：面向解释和调试，保存 agent 的证据、定位、actions 和失败原因。
- `audit`：面向责任链路，保存最终字段值由谁确认、何时确认、是否人工修改、对应证据来源。

对应关系：

```text
agent ExtractionResult.result
  -> extracted_fields.agent_value_json
  -> route / review 后生成 extracted_fields.final_value_json

agent ExtractionResult.trace
  -> field_traces
  -> review handoff 使用证据和 actions

field final value + route + review + trace refs
  -> field_commits
  -> audit API 返回
```

设计约束：

- review 结果不覆盖 agent 原始结果，只写入 `review_fields` 和 `final_value_json`。
- audit 不重新计算字段值，只记录最终提交时的责任链路。
- trace 不保存人工审核结论；人工审核结论保存在 `reviews` 和 `review_fields`。

## 10. Agent Service HTTP 调用方式

后端通过 HTTP 调用 agent service。第一版可以串行调用三个接口：

```text
上传请求中的原始文件 bytes
  -> POST agent /v1/document-processor/process
  -> ProcessResult(blocks + markdown + md_list)
  -> backend 保存 markdown / md_list / blocks
  -> backend 为 blocks 补 document_id / block_id
  -> POST agent /v1/file-extraction-agent/extract
  -> ExtractionResult(result + trace)
  -> backend 组装 field_outputs + refs_with_text
  -> POST agent /v1/route-policy-agent/evaluate
  -> RoutePolicyResult(field_routes)
```

`agent_client.py` 负责：

- 从 `UploadFile` 读取到的 bytes 构造 multipart 文件，提交给 `document_processor`。
- 将 `ProcessResult.blocks` 转成 `file_extraction_agent` 需要的 `NormalizedBlock[]`。
- 为每个 block 生成稳定 `block_id`，例如 `"{document_id}:p{page_no}:b{index}"`。
- 传入后端选择的 `task_spec`、`run_options` 和 `metadata`。
- 将字段输出和 refs 证据文本提交给 `route_policy_agent`。
- 返回完整 `ExtractionResult` 和 `RoutePolicyResult` 给 `task_service`。

异常处理：

```text
agent HTTP 调用失败
  -> task_service 捕获异常
  -> 写入 tasks.error_message
  -> 任务进入 failed

agent 返回 ExtractionResult.status=failed
  -> 保存 agent_runs / field_traces
  -> route_policy_agent 判断 review / reject / failed
```

## 11. 本科毕业设计原型范围

第一版需要实现完整闭环，但不追求生产级复杂度。

需要覆盖：

- 单文件 PDF / DOCX 上传。
- 单任务创建、状态查询、result、trace、review、audit。
- SQLite 本地数据库。
- SQLite 保存 markdown、blocks、trace 和审核结果，不保存用户上传的原始文件。
- HTTP 调用 agent service 的 document_processor、file_extraction_agent 和 route_policy_agent。
- 人工审核 `approve / revise_and_approve / reject`。
- 字段级 audit 展示。

暂不覆盖：

- 登录、权限、多用户。
- 批量任务。
- 取消任务。
- 重试任务。
- 分布式任务队列。
- 复杂数据库迁移。
- 多轮人工补料或重新抽取。
