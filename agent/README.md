# Agent Service

`agent/` 提供文档处理与字段抽取服务，供 `backend` 调用。

## Overview

- 接收 `pdf`、`docx` 等文档输入
- 调用 `document_processor` 做文档标准化
- 调用 `file_extraction_agent` 做字段抽取
- 通过 HTTP 接口对外提供服务

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

`document_processor` 的 PDF 路径默认使用 `docling + RapidOCR`。为了让模型下载产物跟 `impl/pdf` 这块能力放在一起，同时避免散落到每台机器自己的默认用户目录，当前实现会在运行时自动把目录收口到 [`agent/document_processor/impl/pdf/models`](./agent/document_processor/impl/pdf/models)：

```text
./agent/document_processor/impl/pdf/models
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

### `document_processor`

负责把原始文档处理成统一的 Markdown 和 block 结果，给后续抽取使用。

文档见：

- [document_processor/README.md](document_processor/README.md)
- [document_processor/docs/DESIGN.md](document_processor/docs/DESIGN.md)

### `file_extraction_agent`

负责在标准化后的多文档内容上做字段抽取，输出候选和最终结果。

更具体的实现边界和流程说明见 [docs/DESIGN.md](docs/DESIGN.md)。
