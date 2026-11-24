# 设计文档与模块决策总目

本页汇总全仓设计文档与各模块 `DECISIONS.md`，并标注验证状态（架构总览见 [ARCHITECTURE.md](../../ARCHITECTURE.md)，核心原则见 [core-beliefs.md](core-beliefs.md)）。

状态口径：`已验证` 表示与最近一次源码核对及自动化测试一致；`待更新` 表示代码或测试已变但文档待同步。

## 核心设计原则

- [核心工程原则与设计品味](core-beliefs.md)（状态：已验证，2026-11-24）

## 各包设计与模块决策

| 顶层包 / 子系统 | 一手设计入口 | 模块级决策（`DECISIONS.md`） | 验证状态 |
| --- | --- | --- | --- |
| `agent_proto` | [DESIGN.md](../../agent_proto/docs/DESIGN.md) | [agent_proto/DECISIONS.md](../../agent_proto/DECISIONS.md) | 已验证（2026-11-24） |
| `storage` | [DESIGN.md](../../storage/docs/DESIGN.md) | [storage/core/DECISIONS.md](../../storage/core/DECISIONS.md) | 已验证（2026-11-24） |
| `shared` | [DESIGN.md](../../shared/docs/DESIGN.md) | [shared/traceagent_shared/DECISIONS.md](../../shared/traceagent_shared/DECISIONS.md) | 已验证（2026-11-24） |
| `document_service` | [总设计](../../document_service/docs/DESIGN.md) / [API](../../document_service/docs/API.md) / [processor](../../document_service/document_processor/docs/DESIGN.md) / [resources](../../document_service/document_resources/docs/DESIGN.md) | [processor](../../document_service/document_processor/docs/DECISIONS.md) / [resources](../../document_service/document_resources/docs/DECISIONS.md) | 已验证（2026-11-24） |
| `agent` | [总设计](../../agent/docs/DESIGN.md) / [API](../../agent/docs/API.md) / [问答内核](../../agent/service/file_extraction_agent/docs/DESIGN.md) | [file_extraction_agent](../../agent/service/file_extraction_agent/docs/DECISIONS.md) | 已验证（2026-11-24） |
| `backend` | [DESIGN.md](../../backend/docs/DESIGN.md) / [SESSION_MANAGER.md](../../backend/docs/SESSION_MANAGER.md) / [API.md](../../backend/docs/API.md) / [table.md](../../backend/docs/table.md) | [core](../../backend/core/DECISIONS.md) / [routes](../../backend/routes/DECISIONS.md) / [services](../../backend/services/DECISIONS.md) / [crud](../../backend/crud/DECISIONS.md) | 已验证（2026-11-24，含待修缺陷见 [活动修复计划](../exec-plans/active/backend-bugs-2026-11-24.md)） |
| `frontend` | [DESIGN.md](../../frontend/docs/DESIGN.md) | [lib](../../frontend/src/lib/DECISIONS.md) / [components](../../frontend/src/components/DECISIONS.md) | 已验证（2026-11-24） |
| `scripts` | [local-dev-and-testing.md](../references/local-dev-and-testing.md) / [DEVLOG.md](../../scripts/docs/DEVLOG.md) | [scripts/docs/DECISIONS.md](../../scripts/docs/DECISIONS.md) | 已验证（2026-11-24） |
| `memory` | [DESIGN.md](../../memory/docs/DESIGN.md) | [memory/docs/DECISIONS.md](../../memory/docs/DECISIONS.md) | 已验证（2026-11-24） |
| `.github`（CI） | [DESIGN.md](../../.github/docs/DESIGN.md) | [.github/docs/DECISIONS.md](../../.github/docs/DECISIONS.md) | 已验证（2026-11-24） |

## 维护规则

- 新增模块并引入 `DECISIONS.md` 时，必须同步挂入对应包 `docs/DESIGN.md` 与本页总目（由 `python3 memory/dream_scan.py --audit` 与 `memory/tests/test_dream_scan.py` 机械校验）。
- 仅记录已核实的长期设计与取舍；施工中的暂态方案与未完计划放 [docs/exec-plans/active/](../exec-plans/active/)。
