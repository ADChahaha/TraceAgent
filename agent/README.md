# Agent Service

`agent/` 提供文档标准化、字段抽取和字段级 route policy 三个 HTTP 阶段，供 `backend` 调用。

## Overview

主链路是：

```text
backend 上传 PDF bytes
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

### PDF 处理引擎

`service.document_processor` 当前只处理 PDF，固定走 MinerU pipeline，不保留 Docling、RapidOCR、PaddleOCR 或其他 fallback。处理链路是：

```text
UploadFile
  -> processor.process(file_obj, file_type)
  -> 校验 file_obj.read()、文件名和 PDF 类型
  -> 读取 PDF bytes 并调用 mineru_converter.convert_pdf_bytes_to_content_list(...)
  -> mineru_html 生成 html、display_html、markdown、md_list 和 blocks
  -> 返回 ProcessResult
```

常用配置：

```bash
export MINERU_BIN=mineru
export DOCUMENT_PROCESSOR_MINERU_LANG=japan
export MINERU_API_MAX_CONCURRENT_REQUESTS=1
```

中文 PDF 可以把 `DOCUMENT_PROCESSOR_MINERU_LANG` 设为 `ch`。MinerU 失败会直接向上返回错误，不会自动切换到其他解析引擎。

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
