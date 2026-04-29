# Agent Service

`agent/` 提供文档标准化、字段抽取和字段级 route policy 三个 HTTP 阶段，供 `backend` 调用。

## Overview

主链路是：

```text
backend 上传 PDF / DOCX bytes
  -> service.document_processor 输出 markdown、md_list、blocks、meta_info、warnings
  -> backend 聚合多文档 blocks 并补齐 document_id / block_id
  -> service.file_extraction_agent 执行 broad evidence bundle 和 field resolution
  -> backend 从字段 result/trace 组装 field_outputs + refs_with_text
  -> service.route_policy_agent 判断字段级 accept / review / reject
  -> backend 保存 route、review、final result 和 audit
```

`agent/` 不直接访问 backend 的 SQLite，不执行人工审核，也不写最终业务库；它只返回后端可治理的标准化结果、字段抽取结果和字段 route 决策。

## Quick Start

### 创建环境

```bash
conda create -n agent-gate python=3.11 -y
conda activate agent-gate
```

### 安装依赖

```bash
pip install -e .
```

### PDF 模型目录

`service.document_processor` 的 PDF 路径默认使用 `docling + RapidOCR`。为了让模型下载产物跟 `impl/pdf` 这块能力放在一起，同时避免散落到每台机器自己的默认用户目录，当前实现会在运行时自动把目录收口到 [`agent/service/document_processor/impl/pdf/models`](./agent/service/document_processor/impl/pdf/models)：

```text
./agent/service/document_processor/impl/pdf/models
  -> docling/
  -> huggingface/
  -> rapidocr/
```

对应逻辑是：

```text
首次创建 `PdfProcessor`
  -> 先检查调用方是否显式设置了 `DOCLING_CACHE_DIR`
  -> 再检查是否显式设置了 `RAPIDOCR_MODEL_ROOT`
  -> 再检查是否显式设置了 `HF_HOME` / `HF_HUB_CACHE` / `HUGGINGFACE_HUB_CACHE`
  -> 如果都没设置，就自动把模型目录指到 `impl/pdf/models/`
  -> 然后才延迟导入 docling 并初始化 `DocumentConverter`
```

如果你要覆盖默认位置，可以在启动前自己设置环境变量：

```bash
export DOCLING_CACHE_DIR=/your/path/docling
export RAPIDOCR_MODEL_ROOT=/your/path/rapidocr
export HF_HOME=/your/path/huggingface
```

### Usage

在 `agent/` 目录下执行：

```bash
python -m uvicorn main:app --reload --port 8000
```

启动后可访问：

- 健康检查：`/healthz`
- 接口文档：`/docs`

## 模块说明

### `service.document_processor`

负责把原始文档处理成统一的 Markdown 和 block 结果，给后续抽取使用。

文档见：

- [service/document_processor/README.md](service/document_processor/README.md)
- [service/document_processor/docs/API.md](service/document_processor/docs/API.md)
- [service/document_processor/docs/DESIGN.md](service/document_processor/docs/DESIGN.md)

### `service.file_extraction_agent`

负责在标准化后的多文档内容上做字段抽取，输出字段级 `result + trace`。当前流程包含 broad evidence bundle、field resolution、跨字段/全局补查 action 和 validation rules 后处理。

文档见：

- [service/file_extraction_agent/README.md](service/file_extraction_agent/README.md)
- [service/file_extraction_agent/docs/API.md](service/file_extraction_agent/docs/API.md)
- [service/file_extraction_agent/docs/DESIGN.md](service/file_extraction_agent/docs/DESIGN.md)

### `service.route_policy_agent`

负责字段抽取后的 route policy 判断。它消费 `TaskSpec + field_outputs + refs_with_text`，只基于字段输出和证据文本判断 `accept / review / reject`，不重新抽取字段、不读取完整原文、不生成 audit。

文档见：

- [service/route_policy_agent/docs/DESIGN.md](service/route_policy_agent/docs/DESIGN.md)

更具体的服务级实现边界和流程说明见 [docs/DESIGN.md](docs/DESIGN.md)。
