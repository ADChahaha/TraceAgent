# 技术债与已知限制台账（Tech Debt Tracker）

本页集中跟踪全仓已知待修缺陷、刻意保留的首版妥协与待清理项（单源指针，不在本页复抄详细排查流水）。

## 待修缺陷（高优先级）

- `backend` 9 项已核实稳定性、并发与性能缺陷（`:memory:` 跨线程崩溃、失败工具刷新误判、上传与活跃轮并发、取消收口、流式写事务放大等）：跟踪于活动执行计划 [backend-bugs-2026-11-24.md](active/backend-bugs-2026-11-24.md)。

## 已知架构限制与暂缓优化（低优先级，按需立项）

| 领域 | 已知限制 / 暂缓项 | 来源文档 |
| --- | --- | --- |
| `document_service` | 会话资源按整桶 `documents.zip` 合并发布，逐对象发布与 `raw/` 写入中途失败无远端原子回滚；同桶并发依赖 `backend` 串行化 | [document_service/docs/DESIGN.md](../../document_service/docs/DESIGN.md) / [document_resources/docs/DECISIONS.md](../../document_service/document_resources/docs/DECISIONS.md) |
| `agent` | 每次 `search_embedding` 调用起一次性 OpenVINO 子进程（冷启约 2.3s、峰值约 420MB），暂未引入常驻 worker 池与并发上限 | [file_extraction_agent/docs/DECISIONS.md](../../agent/service/file_extraction_agent/docs/DECISIONS.md) |
| `storage` | 单机本地目录实现，无 S3 Signature v4 鉴权、版本控制、副本、配额、加密与跨节点共享 | [storage/docs/DESIGN.md](../../storage/docs/DESIGN.md) / [storage/core/DECISIONS.md](../../storage/core/DECISIONS.md) |
| `backend` | 单进程单用户部署，无跨进程 manager owner 协调与多租户鉴权；旧 `qa_*` 表不自动迁移 | [backend/services/DECISIONS.md](../../backend/services/DECISIONS.md) / [backend/crud/DECISIONS.md](../../backend/crud/DECISIONS.md) |
| `agent` / `document_service` 联调 | 日常单元测试较多依赖 Fake/Mock，跨服务协议或前端交互变更需在验收标准中补真实运行态端到端验证 | [docs/design-docs/core-beliefs.md](../design-docs/core-beliefs.md) |

## 维护规则

- 某次任务刻意留下的临时妥协或新发现的非本次范围缺陷，当轮登记到本台账或建入 `docs/exec-plans/active/`。
- 已解决的条目从本页移除，具体变更留存对应包 `DEVLOG.md` 与 `docs/exec-plans/completed/`。
