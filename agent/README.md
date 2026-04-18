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
