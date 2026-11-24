# memory 关键决策

归属 [Dreaming 扫描与文档门禁设计](DESIGN.md)，记录跨会话知识沉淀与文档园艺工具的长期取舍。

## 1. 验收驱动开发、面向增加演进与模块级 `DECISIONS.md`（2026-11-24）

- 决定：开发流程改为以用户确认的可观察验收标准为锚点，代码实现坚持"面向增加、谨慎修改既有稳定逻辑"；对话中用户拍板的决策按三要素（做了什么决定、为什么这么选、排除了哪些备选方案）即时落盘到对应包的对应模块 `DECISIONS.md`（独立子模块自带 `docs/` 时放 `<module>/docs/DECISIONS.md`），并同步挂入对应包 `docs/DESIGN.md` 与 `docs/design-docs/index.md`。
- 原因：原微粒度 TDD 易沦为 Agent 贴近内部实现自写单测并自评通过，偏离外部需求；将决策绑定到具体模块可促使代码与文档同步朝增量扩展演进，避免反复修改大总文档或归档遗忘。
- 排除：维持微粒度单测先行门禁；把决策留在归档任务单不管；另建全仓单一 `DECISIONS.md`。

## 2. 收敛为单一 OpenAI Harness 文档体系，Dreaming 转为文档园艺引擎（2026-11-24）

- 决定：删除与 OpenAI Harness 文档重叠的 `memory.md`、`memory/wiki/`、`memory/preference/` 与 `memory/tasks/`，将剩余实用环境参考迁入 `docs/references/local-dev-and-testing.md`、协作写法偏好并入 `docs/design-docs/core-beliefs.md`、待修任务迁入 `docs/exec-plans/active/`；`memory/` 收缩为 Dreaming 跨三端会话扫描、临时草稿（`memory/notes/`）、整理台账（`memory/dream-log.md`）与 Harness 六项门禁脚本（`memory/dream_scan.py`）；`dreaming` 技能改为直接维护更新 `ARCHITECTURE.md`、`docs/` 与各模块 `DECISIONS.md`（仍严禁改动 `AGENTS.md` 与业务源码）。
- 原因：同时保留四层 `memory/` 静态文档与顶层 `ARCHITECTURE.md` / `docs/` 会造成架构、偏好与任务双轨重复，增加维护成本并违背单源去重原则；让 `dreaming` 直接维护 OAI 知识库能把跨会话信号真正沉淀到日常开发必读的一手文档。
- 排除：并行保留 `memory.md` / `memory/wiki/` / `memory/preference/` 与 `docs/` 两套静态知识体系；或者限制 `dreaming` 只能改 `memory/` 而不能同步 `docs/` 与模块 `DECISIONS.md`。
