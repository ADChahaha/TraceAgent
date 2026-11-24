# 服务、文档与常用命令

返回 [memory.md](../../memory.md)。

## 顶层包与文档入口

| 包目录 | 默认地址 | 职责 | 设计与接口入口 |
| --- | --- | --- | --- |
| `agent_proto/` | - | 共享 gRPC 协议（`traceagent-protocol`） | [DESIGN.md](../../agent_proto/docs/DESIGN.md) |
| `storage/` | `127.0.0.1:9000` | 本地 S3 兼容 HTTP 对象存储 | [DESIGN.md](../../storage/docs/DESIGN.md) |
| `shared/` | - | `ObjectStore` / `S3ObjectStore` / 归档封装 | [DESIGN.md](../../shared/docs/DESIGN.md) |
| `document_service/` | `127.0.0.1:8002` | PDF/DOCX 解析、文档树与索引 | [总设计](../../document_service/docs/DESIGN.md) / [解析](../../document_service/document_processor/docs/DESIGN.md) / [资源](../../document_service/document_resources/docs/DESIGN.md) |
| `agent/` | `127.0.0.1:8001` | LangGraph 问答 Agent | [总设计](../../agent/docs/DESIGN.md) / [API](../../agent/docs/API.md) / [内核](../../agent/service/file_extraction_agent/docs/DESIGN.md) |
| `backend/` | `127.0.0.1:8000` | SQLite 持久化、编排与 SSE | [总设计](../../backend/docs/DESIGN.md) / [Manager](../../backend/docs/SESSION_MANAGER.md) / [API](../../backend/docs/API.md) / [表](../../backend/docs/table.md) |
| `frontend/` | `127.0.0.1:3000` | Next.js 工作台、来源管理与数字引用高亮 | [DESIGN.md](../../frontend/docs/DESIGN.md) |

## 本地运行与环境提示

- 安装与启停：[scripts/install.sh](../../scripts/install.sh) / [scripts/start.sh](../../scripts/start.sh) / [README.md](../../README.md)
- CI 口径：[.github/workflows/ci.yml](../../.github/workflows/ci.yml) / [.github/docs/DESIGN.md](../../.github/docs/DESIGN.md)
- 本机测试：`agent`/`document_service`/`backend` 本地回环测试加 `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost` 避开系统代理；前端用 `pnpm --dir frontend test --runInBand`。
- Hugging Face 公开模型下载若因本机 token 报 401，在 `.env` 设 `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`。
- 记忆扫描脚本：[dream_scan.py](../dream_scan.py)（说明见 [memory/docs/DESIGN.md](../docs/DESIGN.md)）。
