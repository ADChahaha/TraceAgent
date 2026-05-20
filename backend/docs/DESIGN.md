# Backend Design

这份文档是 `backend` 的设计入口，面向当前仅保留文档处理、字段抽取、结果提交和审计的实现。接口细节见 [API.md](API.md)。

## 1. 目标与边界

`backend` 负责把 `agent service` 产出的抽取结果变成可治理、可追责的业务任务。它不重新实现 OCR 或字段抽取，而是围绕上传文件、任务状态、最终结果和审计记录组织流程。

任务的真实链路是：

```text
POST /tasks 创建任务
  -> 写入 task.created 事件并返回 task_id / stream.last_event_seq
  -> 前端打开 GET /tasks/{task_id}/events?after_seq=n
  -> backend 后台处理文档、消费 file_extraction_agent NDJSON stream
  -> 每个阶段写入 task_events，前端按 seq 实时渲染或断线补拉
  -> 终态后 result / replay / audit 作为整理后的读模型继续可直接读取
```

核心链路是：

```text
前端或脚本上传一个或多个 PDF + task_type + task_spec
  -> backend 创建任务记录
  -> POST /tasks 立即返回 task_id 和 pending/uploaded
  -> backend 后台继续执行文档处理和字段抽取
  -> backend 通过 HTTP 逐个调用 document_processor，把上传文件转成 markdown + blocks
  -> backend 保存标准化文本结果，不保存原始文件
  -> backend 合并多个文件的 html 作为字段抽取输入，markdown、md_list 和 blocks 留作展示和证据回填
  -> backend 通过 HTTP 调用 file_extraction_agent
  -> agent service 返回 ExtractionResult(result + trace)，其中 trace.source_selectors 保存虚拟 path_id 到原文 DOM id 的映射
  -> task_service 对照 task_spec.fields 补齐 agent 没返回的预期字段，写成 failed/None 占位
  -> backend 直接提交 resolved 字段，failed/None 字段保持未提交
  -> backend 保存抽取结果、trace 和 audit；GET /tasks/{task_id}/replay 会把 trace.source_selectors 原样透传给前端用于 evidence 跳转
```

职责边界：

- `backend` 管理任务、文档标准化结果、数据库记录、最终结果和 audit。
- `agent service` 负责 `document_processor` 和 `file_extraction_agent`，返回标准化结果、字段结果和 trace。
- `backend` 通过 HTTP 调用 `agent service`，不直接 import `agent/` 内部包。
- `backend` 不持久化用户上传的原始文件；上传文件只在请求处理过程中用于调用 `document_processor`。
- `agent service` 不直接访问 `backend` 的 SQLite 数据库。
- `backend` 不内置业务 task spec，也不从默认目录兜底加载；字段 schema 必须由调用方在 `POST /tasks` 时传入。
- 第一版不做登录、权限、多用户、批量任务、取消任务和重试任务。

## 2. FastAPI 项目结构

当前实现结构如下：

```text
backend/
  pyproject.toml
  main.py
  core/
    config.py
    db.py
    storage.py
  routes/
    tasks.py
    capabilities.py
    errors.py
  crud/
    agent_stage_runs.py
    task_events.py
    tasks.py
    extraction.py
    audit.py
    json_utils.py
  services/
    task_service.py
    agent_client.py
    audit_service.py
    errors.py
    time_utils.py
  models/
    schema.py
  tests/
    test_task_flow.py
    test_task_events.py
    test_config.py
    docs/
  docs/
    API.md
    DESIGN.md
```

模块边界：

- `main.py` 创建 FastAPI app，通过 lifespan 初始化 SQLite 连接、agent client 和服务对象，挂载 `routes/`，不写业务流程。
- `pyproject.toml` 定义 backend 独立 Python 包、运行依赖和测试依赖；从零启动时应先执行 `pip install -e ".[dev]"`。
- `core/config.py` 管理数据库路径、agent service 地址等配置，不管理业务 task spec。
- `core/db.py` 初始化 SQLite 连接，不直接写业务查询。
- `core/storage.py` 只保留上传文件元信息所需的哈希工具，不落盘保存原始文件。
- `routes/` 只做 HTTP 入参出参适配，把请求转交给 `services/`。
- `models/schema.py` 定义 SQLite DDL。第一版没有引入 ORM，CRUD 直接使用 `sqlite3.Row` 和参数化 SQL。
- `crud/` 封装基础数据库读写，不写业务编排。
- `services/` 负责任务创建、agent 调用、状态流转和 audit。

## 3. 主处理链路

任务创建后的处理流程如下：

```text
POST /tasks 上传一个或多个文件
  -> routes.tasks 接收 files/file、task_type、task_spec、metadata
  -> routes.tasks 在当前请求中读取每个上传文件 bytes
  -> task_service 校验至少一个文件、逐个校验文件类型和外部传入的 task_spec
  -> SQLite 写入 tasks，状态为 pending / uploaded
  -> POST /tasks 先返回 task_id/status/stage/error_message
  -> FastAPI BackgroundTasks 调用 task_service.run_created_task(...)
  -> task_service 将任务置为 processing / document_processing
  -> agent_client 逐个用上传文件 bytes 通过 HTTP 调用 agent service 的文档处理接口
  -> document_processor 输出语义 HTML 时只需保留 heading 层级和 block 阅读顺序
  -> SQLite 为每次 document_processor 调用写入 agent_stage_runs，不保存原始文件 bytes
  -> task_service 为每个文件生成 document_id，并为 blocks 补 document_id / block_id
  -> SQLite 为每个文件写入 documents(markdown / md_list_json / blocks_json / meta_info_json / warnings_json)
  -> task_service 合并全部 html 作为字段抽取输入，同时保留 markdown、md_list 和 blocks
  -> agent_client 再通过 HTTP 调用 agent service 的字段抽取接口，发送文档 html、task_spec 和可选 run_options
  -> file_extraction_agent 按 heading stack 重建虚拟 section 树
  -> SQLite 为 file_extraction_agent 调用写入 agent_stage_runs
  -> SQLite 写入 agent_runs / extracted_fields / field_traces；task_spec 中存在但 agent 未返回的字段会补 failed/None 占位
  -> backend 直接提交 resolved 字段
  -> backend 保存抽取结果、trace 和 audit
  -> 如果 agent 或流程失败，将任务置为 failed / done 并保存 error_message
  -> GET /tasks/{task_id} 返回当前 status/stage/error_message，供前端轮询
```

工作台任务列表流程如下：

```text
GET /tasks?limit=20
  -> routes.tasks 读取可选 limit 参数
  -> task_service 把 limit 限制在 1..100
  -> crud.tasks 按 updated_at DESC、created_at DESC、id DESC 读取最近任务
  -> task_service 对每条任务复用单任务 summary 序列化
  -> 查询 extracted_fields、field_traces
  -> 补齐 has_result、has_trace 和错误信息
  -> 返回 { "tasks": TaskSummary[] }
```

第一版任务执行模型是“请求内创建、后台处理”：`POST /tasks` 只保证任务已经入库并返回 `pending/uploaded`，耗时的 document processing 和 extraction 在响应发出后继续执行。调用方需要轮询 `GET /tasks/{task_id}` 获取 `completed/done` 或 `failed/done`；失败原因统一从 summary 的 `error_message` 读取。

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
  -> FastAPI 解析 files/file/Form 参数
  -> task_spec 和 metadata 如果存在就按 JSON object 解析
  -> 读取每个上传文件 bytes
  -> 调用 task_service / audit_service
  -> 返回服务层已组装的 API 响应
```

### `routes.capabilities`

暴露 `GET /capabilities`，返回支持文件类型、空任务类型列表和 feature flags。因为 backend 不内置业务 schema，`task_types` 固定为空，调用方根据 `features.external_task_spec=true` 自行传入 `task_spec`。

### `crud`

`crud/` 只负责最基础的数据库读写，也就是创建、查询、更新和删除记录。它不决定业务流程，不调用 agent service，也不执行任何人工复核流程。

数据库访问链路应当保持为：

```text
routes
  -> services
  -> crud
  -> models / SQLite
```

不要让 `routes/` 直接操作 `models/`，也不要把复杂业务流程塞进 `crud/`。例如“什么时候调用 agent、什么时候提交字段、什么时候生成 audit”属于 `services/`。

第一版不按每张表机械拆文件，而是按业务聚合拆：

```text
crud/tasks.py
  -> tasks
  -> documents

crud/agent_stage_runs.py
  -> agent_stage_runs

crud/task_events.py
  -> task_events

crud/extraction.py
  -> agent_runs
  -> extracted_fields
  -> field_traces

crud/audit.py
  -> field_commits
```

## 5. 后端序列化

### `GET /tasks/{task_id}`

返回任务当前快照：

```json
{
  "task_id": "task_xxx",
  "status": "completed",
  "stage": "done",
  "error_message": null,
  "has_result": true,
  "has_trace": true,
  "stream": {
    "state": "ended",
    "last_event_seq": 8
  }
}
```

`has_result` 和 `has_trace` 都只根据数据库里是否有对应记录判断；这里不再返回额外的审核标记。

### `GET /tasks/{task_id}/result`

返回字段结果和是否已提交的标记：

```json
{
  "task_id": "task_xxx",
  "status": "completed",
  "fields": [
    {
      "field_name": "room_numbers",
      "display_name": "文明寝室房间号",
      "agent_value": "1-101,1-102",
      "final_value": "1-101,1-102",
      "field_status": "resolved",
      "source": "agent",
      "committed": true
    }
  ]
}
```

只有 `agent_status == "resolved"` 的字段才会写入 `final_value` 和 audit。`failed` 或缺失字段保留为 `final_value=null`、`source="none"`、`committed=false`。

### `GET /tasks/{task_id}/trace`

返回文档处理和字段抽取的 trace 视图：

```text
documents
  -> agent_runs
  -> agent_stage_runs
  -> field_traces
  -> trace.steps / trace.fields / metadata
```

trace 只展示 document_processing 和 extraction 两段。

### `GET /tasks/{task_id}/replay`

返回前端回放工作台需要的整理视图：

```text
agent_run.trace_json
  -> outline_tree / actions / field_states
  -> source_selectors(path_id -> 原文 DOM id)
agent_stage_runs(document_processor)
  -> display_html
  -> 过滤页码、页眉、页脚版本号等旧任务文档 chrome
```

`source_selectors` 不参与字段判定，只用于前端把 `evidence://0000.0001...` 这类虚拟 locator 定位到 `display_html` 里的真实 DOM 节点。backend 不重新生成这张表，只透传 file_extraction_agent trace 中的映射。

### `GET /tasks/{task_id}/audit`

返回字段提交记录。每条 commit 只记录抽取结果和提交元数据。

## 6. 状态模型

任务业务状态 `status`：

```text
pending
processing
completed
failed
```

任务处理阶段 `stage`：

```text
uploaded
document_processing
extraction
done
```

没有额外的审核阶段。

## 7. 事件模型

任务事件必须持久化，不能只放在内存里。每个事件使用任务内递增的 `seq` 作为续传游标。

推荐事件类型：

```text
task.created
task.stage_changed
document.processed
agent.event
field.written
task.completed
task.failed
```

`agent.event` 用于承载 agent service 的原始或归一化 stream 事件，例如 `tool_started`、`tool_completed`、`tool_failed`、`candidate_evidence_added`、`field_written` 和 `result_completed`。

## 8. 数据表

任务表只保留 `pending / processing / completed / failed` 状态和 `uploaded / document_processing / extraction / done` 阶段。抽取结果表保留 `agent_value`、`final_value`、`source` 和 `committed`，不再有审核字段。

字段过程和审计记录都从 `field_traces`、`extracted_fields` 和 `field_commits` 派生，不再依赖额外的审核表。

## 9. 已删除的部分

当前实现没有单独的人工审核接口、审核状态或审核表。
