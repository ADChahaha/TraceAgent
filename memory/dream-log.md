# Dreaming 整理记录

last_dream_at: 2026-11-24T23:24:00+08:00

---

## 2026-11-24 全量回溯 140 个 Codex 历史会话（2026-04-08 至 2026-10-02）

通过 34 切片并行挖掘 + 6 领域源码核实，逐条筛除早期已废架构并核对当前源码（336 条候选核实归并）：
- 顶层架构与通用文档：补齐 [ARCHITECTURE.md](../ARCHITECTURE.md)（含修正漏写的 `ReadBlocks`、多轮文档 QA 定位、SQLite/二进制隔离与 `backend` 终态唯一裁决权）、[core-beliefs.md](../docs/design-docs/core-beliefs.md)、[document-qa-workbench.md](../docs/product-specs/document-qa-workbench.md)、[local-dev-and-testing.md](../docs/references/local-dev-and-testing.md) 与 [tech-debt-tracker.md](../docs/exec-plans/tech-debt-tracker.md)。
- 模块级 `DECISIONS.md`：更新 `agent_proto`、`document_processor`、`document_resources`、`file_extraction_agent`、`backend/services`、`backend/crud`、`frontend/src/lib`、`frontend/src/components` 8 份既有决策文档，新设 `backend/core`、`backend/routes`、`scripts/docs` 与 `.github/docs` 4 份模块决策并全部挂入 [docs/design-docs/index.md](../docs/design-docs/index.md)（全仓共 15 份 `DECISIONS.md`）。
- 文档漂移修正：修复 `agent` 3 处过时的 `service/object_store` 引用至 `traceagent_shared.object_store`，并在 `events-and-model.md` 补全 `8.0s` 默认超时与 `.env` 优先级。

## 2026-11-24 合并去重至 OpenAI Harness 文档体系

将原四层记忆体系中与 OpenAI Harness 文档重叠的 `memory.md`、`memory/wiki/`、`memory/preference/` 与 `memory/tasks/` 全部迁并清理，[dreaming/SKILL.md](../.agents/skills/dreaming/SKILL.md) 与 [dream_scan.py](dream_scan.py) 升级为面向 [ARCHITECTURE.md](../ARCHITECTURE.md)、`docs/` 与全仓模块 `DECISIONS.md` 的文档园艺与六项门禁审计工具。
