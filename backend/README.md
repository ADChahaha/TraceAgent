# Backend

`backend` 是毕业设计原型中的任务治理服务。它接收前端或脚本上传的一个或多个 PDF / DOCX、`task_type` 和外部传入的 `task_spec`，调用 `agent service` 完成文档标准化、字段抽取和字段级 route policy，然后把任务状态、最终结果、人工复核和审计记录保存在本地 SQLite。

## 实现链路

```text
上传一个或多个 PDF / DOCX + task_type + task_spec
  -> FastAPI `POST /tasks` 读取每个文件 bytes
  -> 校验文件类型和 task_spec，创建 tasks 记录
  -> 逐个 HTTP 调用 agent service 的 document_processor
  -> 每个文件生成 document_id，并保存 markdown、md_list、blocks 和处理元信息，不保存原始文件
  -> 合并多个文件的 markdown、md_list 和 blocks
  -> HTTP 调用 file_extraction_agent
  -> 保存 agent_runs、extracted_fields 和 field_traces
  -> 组装 field_outputs + refs_with_text
  -> HTTP 调用 route_policy_agent
  -> 保存 field_routes
  -> accept 自动写 field_commits 并完成任务
  -> review 返回 handoff，等待 `POST /tasks/{task_id}/review`
  -> reject 或失败写入终态和错误信息
```

第一版采用同步处理：`POST /tasks` 会在同一个请求内跑完 document processing、extraction 和 route policy，响应中的 `status/stage` 可能已经是 `completed/done`、`waiting_review/review`、`rejected/done` 或 `failed/done`。

## 主要 API

```text
POST /tasks
GET  /tasks/{task_id}
GET  /tasks/{task_id}/result
GET  /tasks/{task_id}/trace
GET  /tasks/{task_id}/review
POST /tasks/{task_id}/review
GET  /tasks/{task_id}/audit
GET  /capabilities
```

详细请求和响应见 [`docs/API.md`](docs/API.md)，设计边界见 [`docs/DESIGN.md`](docs/DESIGN.md)。

## 运行

### 安装依赖

`backend` 有独立的 Python 依赖入口。第一次运行前，从仓库根目录执行：

```bash
conda activate agent-gate
cd backend
pip install -e ".[dev]"
cd ..
```

默认配置：

- SQLite：`backend/backend.sqlite3`
- Agent service：`http://localhost:8001`

可用环境变量覆盖：

```text
BACKEND_DATABASE_PATH=/path/to/backend.sqlite3
AGENT_SERVICE_BASE_URL=http://localhost:8001
AGENT_SERVICE_TIMEOUT_SECONDS=1200
```

`backend` 不内置任何业务 task spec，也不从默认目录兜底加载。调用方必须在 `POST /tasks` 的 multipart 表单中传入 `task_spec` JSON。新版上传字段为可重复的 `files`，旧版单文件 `file` 字段仍兼容。

启动方式：

```bash
AGENT_SERVICE_BASE_URL=http://127.0.0.1:8001 uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

## 测试

后端测试使用 fake agent client，不依赖真实 OCR、LLM 或 agent service：

```bash
PYTHONPATH=. pytest backend/tests -q
```
