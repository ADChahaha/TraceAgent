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
cd agent
pip install -e ".[dev]"
cd ../backend
pip install -e ".[dev]"
cd ..
```

安装前端依赖：

```bash
cd /path/to/agent_gate
cd frontend
pnpm install
cd ..
```

如果要连接真实 LLM，在启动 `agent` 前设置模型服务环境变量：

```bash
export BASE_URL="https://your-model-endpoint/v1"
export OPENAI_API_KEY="your-api-key"
export MODEL="your-model-name"
```

如果要处理真实 PDF，尤其是扫描件或带坏 OCR/text layer 的表格 PDF，也应在启动 `agent` 前设置 PDF 抽取配置。默认链路是跨平台的 `docling + RapidOCR + onnxruntime`：

```bash
export DOCUMENT_PROCESSOR_RAPIDOCR_BACKEND=onnxruntime
export DOCUMENT_PROCESSOR_RAPIDOCR_ONNX_USE_COREML=0
```

对文本层很差的 PDF，可以强制整页 OCR；例如论文替代名单这类 8 页表格 PDF，开启后末页序号、学号和姓名抽取更稳定：

```bash
export DOCUMENT_PROCESSOR_RAPIDOCR_FORCE_FULL_PAGE_OCR=1
```

PDF 相关配置在 `agent service` 启动时读取，修改后需要重启 `agent` 才会生效。常用配置如下：

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `DOCUMENT_PROCESSOR_RAPIDOCR_BACKEND` | `onnxruntime` | RapidOCR 后端，支持 `onnxruntime`、`openvino`、`paddle`、`torch`。 |
| `DOCUMENT_PROCESSOR_RAPIDOCR_ONNX_USE_COREML` | `0` | 是否让 onnxruntime 尝试 CoreML；当前样本上不建议默认开启。 |
| `DOCUMENT_PROCESSOR_RAPIDOCR_FORCE_FULL_PAGE_OCR` | `0` | 是否忽略 PDF 内置文本层并整页 OCR，适合坏文本层或扫描件。 |
| `DOCUMENT_PROCESSOR_PDF_TABLE_DO_CELL_MATCHING` | `1` | docling 表格 cell matching；密集表格列粘连时可临时设为 `0` 做对照。 |
| `DOCUMENT_PROCESSOR_DOCLING_DEVICE` | docling 默认值 | docling 加速设备，例如 `cpu` 或 `mps`。 |
| `DOCUMENT_PROCESSOR_DOCLING_NUM_THREADS` | docling 默认值 | docling 线程数，必须是正整数。 |
| `DOCUMENT_PROCESSOR_PDF_OCR_BATCH_SIZE` | docling 默认值 | OCR batch size，必须是正整数。 |
| `DOCUMENT_PROCESSOR_PDF_LAYOUT_BATCH_SIZE` | docling 默认值 | layout batch size，必须是正整数。 |
| `DOCUMENT_PROCESSOR_PDF_TABLE_BATCH_SIZE` | docling 默认值 | table batch size，必须是正整数。 |

模型缓存默认写到 `agent/service/document_processor/impl/pdf/models/` 下；可用 `DOCLING_CACHE_DIR`、`RAPIDOCR_MODEL_ROOT`、`HF_HOME` 覆盖。更完整的 PDF 引擎说明见 `agent/service/document_processor/README.md`。

### 2. 启动 agent service

新开一个终端：

```bash
conda activate agent-gate
cd /path/to/agent_gate
cd agent
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

启动后可访问：

- `http://127.0.0.1:8001/healthz`
- `http://127.0.0.1:8001/docs`

### 3. 启动 backend

再开一个终端：

```bash
conda activate agent-gate
cd /path/to/agent_gate
AGENT_SERVICE_BASE_URL=http://127.0.0.1:8001 uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

backend 默认使用本地 SQLite，数据库文件为 `backend/backend.sqlite3`。如需改路径：

```bash
BACKEND_DATABASE_PATH=/private/tmp/agent_gate.sqlite3 \
AGENT_SERVICE_BASE_URL=http://127.0.0.1:8001 \
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

### 4. 启动 frontend

再开一个终端：

```bash
cd /path/to/agent_gate
cd frontend
BACKEND_BASE_URL=http://127.0.0.1:8000 pnpm dev -- --port 3000
```

打开：

```text
http://127.0.0.1:3000/
```

如果 `3000` 被占用，可以改用：

```bash
BACKEND_BASE_URL=http://127.0.0.1:8000 pnpm dev -- --port 3002
```

然后打开 `http://127.0.0.1:3002/`。

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

## 目录规划

```text
.
├── README.md
├── frontend/
├── backend/
└── agent/
```
