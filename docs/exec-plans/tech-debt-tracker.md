# 技术债与已知限制台账（Tech Debt Tracker）

本页集中跟踪全仓已知待修缺陷、刻意保留的首版妥协与待清理项（单源指针，不在本页复抄详细排查流水）。

## 待修缺陷（中高优先级）

- `frontend` 尾随来源段截断风险：`splitTrailingSourcesSection`（[markdown-evidence.tsx](../../frontend/src/components/markdown-evidence.tsx) L155-L178）在 `citation` 模式下倒序命中 `Sources`/`References`/`来源`/`引用` 标题即无条件丢弃后续全部内容，未校验该节是否仅含引用链接列表，存在误删合法正文末尾小节风险。

## 已知架构限制与待清理项（低优先级，按需立项）

| 领域 | 已知限制 / 待清理项 | 来源文档 / 源码 |
| --- | --- | --- |
| `document_service` | 会话资源按整桶 `documents.zip` 合并发布，逐对象发布与 `raw/` 写入中途失败无远端原子回滚；同桶并发依赖 `backend` 串行化 | [document_service/docs/DESIGN.md](../../document_service/docs/DESIGN.md) / [document_resources/docs/DECISIONS.md](../../document_service/document_resources/docs/DECISIONS.md) |
| `document_service` | PDF MinerU 3.1.6 `pipeline` 标题层级偏粗、目录页降级散行；`markdown_is_body_subheading` 留有少量日语简章轻量规则，[html.py](../../document_service/document_processor/pdf/html.py) 残留未消费的 `markdown_layout_features`；PDF/MinerU 端到端全链路实测待补 | [document_processor/docs/DECISIONS.md](../../document_service/document_processor/docs/DECISIONS.md) |
| `agent` | 每次 `search_embedding` 调用起一次性 OpenVINO 子进程（冷启约 2.3s、峰值约 420MB），暂未引入常驻 worker 池与并发上限；第三方中转偶发断流与缺失终态信号目前仅靠图内 5 次重试恢复 | [file_extraction_agent/docs/DECISIONS.md](../../agent/service/file_extraction_agent/docs/DECISIONS.md) |
| `agent` 遗留清理 | [agent/pyproject.toml](../../agent/pyproject.toml) L17 残留未使用依赖 `hdbscan>=0.8,<1`；[messages.py](../../agent/service/file_extraction_agent/core/messages.py) L39-L40 列出 `ls / grep / read` 未列 `search_embedding`（待核）；[test_loop.py](../../agent/tests/file_extraction_agent/test_loop.py) L162-L199 残留英文 system prompt 原文子串快照断言 | [core-beliefs.md](../design-docs/core-beliefs.md) |
| `storage` | 单机本地目录实现，无 S3 Signature v4 鉴权、版本控制、副本、配额、加密与跨节点共享 | [storage/docs/DESIGN.md](../../storage/docs/DESIGN.md) / [storage/core/DECISIONS.md](../../storage/core/DECISIONS.md) |
| `backend` | 单进程单用户部署，无跨进程 manager owner 协调与多租户鉴权；旧 `qa_*` 表不自动迁移；[backend/pyproject.toml](../../backend/pyproject.toml) L8 残留旧描述 `Backend governance API for Agent Gate.` | [backend/services/DECISIONS.md](../../backend/services/DECISIONS.md) / [backend/crud/DECISIONS.md](../../backend/crud/DECISIONS.md) |
| `frontend` 死代码 | 未接入当前生产路由的旧组件与模块待清理：`replay-review.tsx`（2518 行）、`outline-panel.tsx`、`task-store.ts`、`types.ts`、`json.ts`、空目录 `src/app/experiments/contract-nli/`、未用 `useRightSidebarResize` 及对应旧样式与测试断言 | [frontend/src/components/DECISIONS.md](../../frontend/src/components/DECISIONS.md) |
| `scripts` | [scripts/start.sh](../../scripts/start.sh) 仅 `sleep 1` 检查 PID 存活，未做 gRPC Health / HTTP `/healthz` 就绪轮询 | [scripts/docs/DECISIONS.md](../../scripts/docs/DECISIONS.md) |
| 跨服务联调 | 日常单元测试较多依赖 Fake/Mock，跨服务协议或前端交互变更需在验收标准中补真实运行态端到端验证 | [core-beliefs.md](../design-docs/core-beliefs.md) |

## 维护规则

- 某次任务刻意留下的临时妥协或新发现的非本次范围缺陷，当轮登记到本台账或建入 `docs/exec-plans/active/`。
- 已解决的条目从本页移除，具体变更留存对应包 `DEVLOG.md` 与 `docs/exec-plans/completed/`。
