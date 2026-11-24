# memory 关键决策

归属 [记忆与 Dreaming 脚本设计](DESIGN.md)，记录项目记忆与协作流程的长期取舍。

## 1. 四层按需记忆与六项程序化门禁

- 决定：保留控制面 `AGENTS.md` 与记忆面分离，活跃记忆按 L0 -> L1 -> L2 -> L3 四层按需加载，由 `memory/dream_scan.py --audit` 执行断链、预算、越层、互链墙、可达性与受保护哈希六项门禁。
- 原因：防止规则和跨会话知识随时间膨胀稀释模型注意力，避免靠人工自觉维持结构整洁。
- 排除：把所有规则与背景知识平铺进单一长 `AGENTS.md`，或取消机械化预算与断链校验。

## 2. 验收驱动开发、面向增加演进与模块级 `DECISIONS.md`（2026-11-24）

- 决定：开发流程改为以用户确认的可观察验收标准为锚点，代码实现坚持"面向增加、谨慎修改既有稳定逻辑"；对话中用户拍板的决策按三要素（做了什么决定、为什么这么选、排除了哪些备选方案）即时落盘到对应包的对应模块 `DECISIONS.md`（独立子模块自带 `docs/` 时放 `<module>/docs/DECISIONS.md`），并同步挂入对应包 `docs/DESIGN.md` 与 `docs/design-docs/index.md`。
- 原因：原微粒度 TDD 易沦为 Agent 贴近内部实现自写单测并自评通过，偏离外部需求；将决策绑定到具体模块可促使代码与文档同步朝增量扩展演进，避免反复修改大总文档或归档遗忘。
- 排除：维持微粒度单测先行门禁；把决策留在归档任务单不管；另建全仓单一 `DECISIONS.md`。

## 3. 引入 OpenAI Harness 顶层知识目录并与四层记忆分层协作（2026-11-24）

- 决定：建立顶层 `ARCHITECTURE.md`（领域地图与单向分层）、`docs/design-docs/`（全仓设计与模块 `DECISIONS.md` 验证状态总目 + `core-beliefs.md`）、`docs/product-specs/`（纯用户视角产品规格）与 `docs/exec-plans/`（`active/`、`completed/`、`tech-debt-tracker.md`）；工程执行计划从 `memory/tasks/` 迁入 `docs/exec-plans/active/`，并新增 `memory/tests/test_docs_harness.py` 机械校验链接完整性、全仓 `DECISIONS.md` 收录与归档任务单的决策迁出标注；`memory/` 专注跨会话四层记忆与 Dreaming，`memory/tasks/` 保留空目录以兼容旧审计脚本契约。
- 原因：分离"产品做什么（product-specs）"、"技术怎么建与原则（ARCHITECTURE / design-docs / 各模块 DECISIONS）"、"当前施工与债务（exec-plans）"与"跨会话记忆（memory）"，既消除概念混杂，又通过结构测试把知识库完整性机械锁死。
- 排除：把所有包设计文档和模块 `DECISIONS.md` 从各包搬回根 `docs/design-docs/`（会破坏模块就近与面向增加）；同时在 `memory/tasks/` 与 `docs/exec-plans/active/` 双写任务单（违背单源原则）；删除 `memory/tasks/` 破坏 `dream_scan.py` 既有测试接口。
