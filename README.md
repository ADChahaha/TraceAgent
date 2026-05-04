# Agent Gate

## Overview

Agent Gate 是一个面向毕业设计 MVP 的文档抽取可信治理系统，由 `frontend`、`backend` 和 `agent` 三层组成。

它不把 LLM 抽取结果直接视为可写库答案，而是把字段结果拆成可追踪、可审核、可路由的治理对象。当前主链路已经覆盖文档上传、文档标准化、字段抽取、route policy、人工复核、字段级提交和审计留痕。

当前 MVP 的基本流程是：

```text
前端上传一个或多个 PDF / DOCX + task_type + task_spec
  -> backend 创建任务并调用 agent service
  -> document_processor 输出 markdown、md_list、blocks 和处理元信息
  -> file_extraction_agent 执行 broad evidence bundle 和 field resolution
  -> route_policy_agent 输出字段级 accept / review / reject
  -> backend 保存 result、trace、review、audit 和字段级提交记录
  -> frontend 展示结果、证据、复核入口、agent 执行过程和审计记录
```

这个流程服务于“写库前治理”：字段只有在 route policy 自动通过，或人工复核确认后，才进入最终提交记录。

## Quickstart

### 1. 准备环境

以下命令默认从仓库根目录执行。新开终端时，先把 `/path/to/agent_gate` 替换为本机仓库路径并进入仓库根目录。

建议先在本地创建一个名为 `agent-gate` 的 Conda 环境，并在后续开发或运行时始终使用它：

```bash
conda create -n agent-gate python=3.11 -y
conda activate agent-gate
```

安装 Python 依赖：

```bash
cd /path/to/agent_gate
pip install -e "agent[dev]"
pip install -e "backend[dev]"
```

安装前端依赖：

```bash
cd /path/to/agent_gate
pnpm --dir frontend install
```

### 2. 配置运行环境

三层服务各自读取不同环境变量。`BASE_URL` 是 `agent service` 调 LLM 的地址；`AGENT_SERVICE_BASE_URL` 是 `backend` 调本地 `agent service` 的地址，不是同一个东西。

端口约定：

| 服务 | 默认地址 | 说明 |
| --- | --- | --- |
| `agent service` | `http://127.0.0.1:8001` | 文档处理、字段抽取和 route policy HTTP API。 |
| `backend` | `http://127.0.0.1:8000` | 任务、结果、review、audit API。 |
| `frontend` | `http://127.0.0.1:3000` | 浏览器工作台。 |

#### Agent service / LLM

如果要连接真实 LLM，在启动 `agent service` 前设置模型服务环境变量：

```bash
export BASE_URL="https://your-model-endpoint/v1"
export OPENAI_API_KEY="your-api-key"
export BROAD_MODEL="your-broad-model-name"
export RESOLUTION_MODEL="your-resolution-model-name"
export ROUTE_POLICY_MODEL="your-route-policy-model-name"
```

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `BASE_URL` | 无 | `agent service` 调用 OpenAI-compatible LLM endpoint 的地址。 |
| `OPENAI_API_KEY` | 无 | LLM endpoint 的 API key。 |
| `BROAD_MODEL` | 无 | `file_extraction_agent` 的 broad planning 模型。 |
| `RESOLUTION_MODEL` | 无 | `file_extraction_agent` 的 field resolution 模型。 |
| `ROUTE_POLICY_MODEL` | 无 | `route_policy_agent` 的 route 判断模型。 |

如果要处理真实 PDF，尤其是扫描件或带坏 OCR/text layer 的表格 PDF，当前默认链路是 MinerU pipeline。需要先确保 `mineru` CLI 在 `agent-gate` 环境中可执行，或显式指定路径：

```bash
export MINERU_BIN="mineru"
export DOCUMENT_PROCESSOR_MINERU_LANG="japan"
```

中文 PDF 可以把语言改成 `ch`：

```bash
export DOCUMENT_PROCESSOR_MINERU_LANG="ch"
```

MinerU 相关配置在 `agent service` 启动时读取，修改后需要重启 `agent` 才会生效。常用配置如下：

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `MINERU_BIN` | `mineru` | MinerU CLI 可执行文件。 |
| `DOCUMENT_PROCESSOR_MINERU_LANG` | `japan` | MinerU OCR 语言参数，例如日文 `japan`、中文 `ch`。 |
| `MINERU_API_MAX_CONCURRENT_REQUESTS` | `1` | 本地 MinerU API 并发数，默认保守。 |
| `MINERU_PROCESSING_WINDOW_SIZE` | MinerU 默认值 | 可选的 MinerU processing window size。 |

MinerU 模型缓存由 MinerU 自身管理。更完整的 PDF 引擎说明见 `agent/service/document_processor/README.md`。

#### Backend

backend 读取这些环境变量：

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `AGENT_SERVICE_BASE_URL` | `http://localhost:8001` | backend 调用本地 `agent service` 的 HTTP 地址。 |
| `AGENT_SERVICE_TIMEOUT_SECONDS` | `1200` | backend 调用 `agent service` 的 HTTP 超时时间；PDF 处理、MinerU 或 LLM 较慢时需要调大。 |
| `BACKEND_DATABASE_PATH` | `backend/backend.sqlite3` | SQLite 数据库文件路径。 |

#### Frontend

frontend 读取这些环境变量：

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `BACKEND_BASE_URL` | `http://localhost:8000` | Next.js API route 转发到 backend 的地址。 |

### 3. 启动 agent service

新开一个终端：

```bash
conda activate agent-gate
cd /path/to/agent_gate
python -m uvicorn --app-dir agent main:app --reload --host 127.0.0.1 --port 8001
```

启动后可访问：

- `http://127.0.0.1:8001/healthz`
- `http://127.0.0.1:8001/docs`

### 4. 启动 backend

再开一个终端：

```bash
conda activate agent-gate
cd /path/to/agent_gate
AGENT_SERVICE_BASE_URL=http://127.0.0.1:8001 \
AGENT_SERVICE_TIMEOUT_SECONDS=1200 \
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

backend 默认使用本地 SQLite，数据库文件为 `backend/backend.sqlite3`。如需改路径：

```bash
BACKEND_DATABASE_PATH=/private/tmp/agent_gate.sqlite3 \
AGENT_SERVICE_BASE_URL=http://127.0.0.1:8001 \
AGENT_SERVICE_TIMEOUT_SECONDS=1200 \
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

### 5. 启动 frontend

再开一个终端：

```bash
cd /path/to/agent_gate
BACKEND_BASE_URL=http://127.0.0.1:8000 \
pnpm --dir frontend dev --port 3000
```

打开：

```text
http://127.0.0.1:3000/
```

如果 `3000` 被占用，可以改用：

```bash
BACKEND_BASE_URL=http://127.0.0.1:8000 \
pnpm --dir frontend dev -- --port 3002
```

然后打开 `http://127.0.0.1:3002/`。

### 6. 常见启动问题

- backend 跑真实 PDF 时中途超时：先把 `AGENT_SERVICE_TIMEOUT_SECONDS` 调大，例如 `1800` 或 `2400`。
- backend 连不上 agent service：检查 `AGENT_SERVICE_BASE_URL` 是否指向 `agent service` 的监听地址，例如 `http://127.0.0.1:8001`。
- agent service 调不了模型：检查 `BASE_URL`、`OPENAI_API_KEY` 和对应模型名是否设置在启动 `agent service` 的终端里。
- frontend 页面提示 backend unavailable：检查启动 frontend 时的 `BACKEND_BASE_URL` 是否指向 backend，例如 `http://127.0.0.1:8000`。

## 项目架构

### 前端 `frontend`

负责用户界面相关工作，包括：

- 上传 PDF / DOCX 和外部 `task_spec`
- 查看任务状态、结果、trace、review 和 audit
- 展示 `document_processor`、`file_extraction_agent`、`route_policy_agent` 的执行过程
- 展示 broad 候选 blocks 正文、resolution 字段输出、route validation 和复核证据
- 提交人工复核决策

### 后端 `backend`

负责业务系统和数据层相关工作，包括：

- 提供任务、结果、trace、review、audit 和 capabilities API
- 管理任务状态和 SQLite 数据记录
- 调用 `agent` 的三个 HTTP 阶段
- 持久化标准化文档、字段结果、字段 trace、route 输出、复核记录和字段级 audit
- 根据 `accept / review / reject` 驱动自动提交、人工复核或拒绝流程

### Agent 服务 `agent`

负责文档处理能力相关工作，包括：

- `document_processor`：PDF / DOCX 标准化，输出 blocks 和 markdown
- `file_extraction_agent`：执行 broad evidence bundle、field resolution、tool/action 留痕和 validation rules
- `route_policy_agent`：基于字段输出和证据文本判断 `accept / review / reject`
- 通过 HTTP 接口供 `backend` 调用，不直接访问 backend 数据库

## 服务协作流程

系统的基本流程如下：

1. 前端上传一个或多个文档，并提交 `task_type` 和外部 `task_spec`。
2. 后端接收请求并创建任务，不持久化用户上传的原始文件。
3. 后端逐个调用 `document_processor`，保存 markdown、md_list、blocks 和处理元信息。
4. 后端合并多文档 blocks，调用 `file_extraction_agent` 得到字段级 `result + trace`。
5. 后端组装字段输出和证据文本，调用 `route_policy_agent` 得到字段级 route。
6. `accept` 字段自动生成提交记录；`review` 字段等待人工审核；`reject` 字段终止自动写入。
7. 前端展示完整执行过程、复核 handoff 和字段级 audit。

## 设计目标

- 服务边界清晰
- 字段级结果可追踪、可审核、可追责
- 写库前通过 route policy 分层处置风险
- 人工复核接收证据包，而不是只看到最终字段值
- MVP 保持同步处理和本地 SQLite，避免提前引入生产级复杂度

## 待开发（Maybe）

以下内容不是当前 MVP 的完成条件，只作为后续可能实现的方向：

- 流式返回结果：让 backend / agent service 把文档处理、字段抽取、route policy 和 replay action 增量推给前端，减少长任务等待感。
- 前端接入 LLM 辅助写字段：在创建任务或人工复核时，由前端调用 LLM 根据用户描述生成字段定义、补全字段配置或给出字段值草稿，最终仍由用户确认后提交。

## 目录规划

```text
.
├── README.md
├── frontend/
├── backend/
└── agent/
```
