# Backend

`backend` 是多文档 QA 的会话和事件服务。它接收前端上传的 PDF/DOCX，调用 `agent service` 的 `document_processor` 做文档标准化；用户每次提问时，backend 把已保存的 `documents + messages + memory` 交给 agent 的 document QA chat completion，并把模型过程事件持久化为可续传 SSE。

它不再维护旧的 `task_spec` 字段抽取、字段提交、result/trace/replay/audit API。backend 是多轮 QA 状态事实来源；agent 只执行单次 completion。

## 实现链路

```text
前端上传一个或多个 PDF/DOCX
  -> FastAPI POST /qa/tasks 读取每个文件 bytes
  -> 校验 PDF/DOCX 类型和 metadata
  -> 调 agent document_processor 得到 html / display_html / markdown / blocks
  -> 保存 qa_tasks / qa_documents
  -> 写入 task.created / document.processed / task.ready 事件

用户提交问题
  -> POST /qa/tasks/{task_id}/inputs
  -> 保存 user message 和 turn.created
  -> 读取 qa_documents 组装 documents(filename + html)
  -> 读取 qa_messages 组装多轮 messages
  -> 读取 qa_tasks.memory_json 组装 memory
  -> 调 agent POST /v1/document-qa/chat/completions
  -> 持久化 agent.event，包括 model_message、tool_* 和 completion.*
  -> completion.completed 时保存 assistant message，清理 active_turn_id
  -> 前端通过 GET /qa/tasks/{task_id}/events?after_seq=n 续传事件
```

## 主要 API

```text
POST /qa/tasks
GET  /qa/tasks
GET  /qa/tasks/{task_id}
POST /qa/tasks/{task_id}/inputs
GET  /qa/tasks/{task_id}/events?after_seq=0
POST /qa/tasks/{task_id}/cancel
GET  /capabilities
GET  /healthz
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

启动方式：

```bash
AGENT_SERVICE_BASE_URL=http://127.0.0.1:8001 uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

## 测试

后端测试使用 fake agent client，不依赖真实 OCR 或 LLM：

```bash
PYTHONPATH=. pytest backend/tests -q
```
