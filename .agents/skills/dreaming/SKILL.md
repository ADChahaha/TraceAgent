---
name: dreaming
description: >-
  Manual cross-session knowledge consolidation and doc-gardening skill for this
  repository. Use only when the user explicitly asks to run dreaming,
  consolidate memory, or sync recent session transcripts and memory/notes/ into
  ARCHITECTURE.md, docs/, and module DECISIONS.md files.
---

# Dreaming（跨会话知识沉淀与文档园艺）

当用户显式要求执行 dreaming 或整理跨会话记忆时，按 Orient -> Gather Signal -> Reconcile & Update Docs -> Audit & Commit 扫描近期三端会话记录与 `memory/notes/`，核对真实源码后直接更新仓库的 Harness 文档体系，并清理过时与漂移内容。

## 知识落位路由（单源去重）

每条核实后的结论只落一个权威位置，其他页面只留简短指针，不复抄源码全文或重复规则：

| 知识类型 | 目标落点 | 说明 |
| --- | --- | --- |
| 顶层包边界、端口与单向分层 | [ARCHITECTURE.md](../../../ARCHITECTURE.md) | 仅在顶层服务边界或依赖方向变化时更新 |
| 全仓设计与模块决策索引 | [docs/design-docs/index.md](../../../docs/design-docs/index.md) | 同步验证状态，确保所有模块 `DECISIONS.md` 均被收录 |
| 跨包工程原则与协作写作品味 | [docs/design-docs/core-beliefs.md](../../../docs/design-docs/core-beliefs.md) | 跨任务通用的原则、沟通与文档习惯 |
| 模块级架构与接口取舍 | 对应包模块的 `DECISIONS.md` | 按三要素（做了什么决定、为什么这么选、排除了哪些备选方案）记录，并挂入对应包 `docs/DESIGN.md` 与 `docs/design-docs/index.md` |
| 用户视角产品行为与验收口径 | `docs/product-specs/` | 同步对外功能流程与验收边界，不写内部实现 |
| 活动/归档计划与技术债 | `docs/exec-plans/`（`active/`、`completed/`、[tech-debt-tracker.md](../../../docs/exec-plans/tech-debt-tracker.md)） | 沉淀待修缺陷与限制；归档完结计划前确认 `Decision Log` 已逐条迁出 |
| 本地命令、环境避坑与运维参考 | `docs/references/` | 如 [local-dev-and-testing.md](../../../docs/references/local-dev-and-testing.md) |
| 会中草稿、归档与整理台账 | `memory/notes/`、`memory/archive/`、[memory/dream-log.md](../../../memory/dream-log.md) | 吸收后移出 `notes/`，`dream-log.md` 只留最近 2-3 次摘要 |

## 只读禁区与写作纪律

- 不修改控制面与业务代码：过程中不改动 `AGENTS.md`，也不改动业务源码（`.py` / `.ts` / `.tsx` / `.proto` 等）。
- 实证优先：更新任何文档前必须对照真实源码、`git log` 或测试核实，查不到来源的标注待核。
- 平实文风：中文直接平实，不使用破折号、弯引号和装饰性符号，不堆砌粗体标签或规则腔套话；日期统一写 `YYYY-MM-DD`。

## 执行流程

1. Orient（按需定向）：
   - 先读 [memory/dream-log.md](../../../memory/dream-log.md)（查看 `last_dream_at`）、`memory/notes/`、`docs/exec-plans/active/` 与 [docs/design-docs/index.md](../../../docs/design-docs/index.md)。
   - 不开局全量读取全仓文档；待步骤 2 确定受影响主题后再按需打开目标文件。
2. Gather Signal（采集增量信号 + 门禁体检）：
   - 在仓库根目录运行只读扫描脚本：`python3 memory/dream_scan.py`。
   - 需要展开某条助手长回复或检索关键词时，用 `--session <id> --turn <N>` 或 `--grep <pattern>`；积压较多时用 `--order oldest --since <T> --until <T>` 分批处理。
   - 若扫描报告存在既有门禁违规，本次整理一并修正。
3. Reconcile & Update Docs（核对源码 -> 更新 OAI 文档与模块决策）：
   - 核查增量会话中用户拍板的决策是否已按三要素落盘到对应模块 `DECISIONS.md`、`docs/design-docs/core-beliefs.md` 或 `docs/exec-plans/active/`，漏记的核实源码后直接补齐。
   - 核对 `ARCHITECTURE.md`、`docs/design-docs/index.md`、`docs/product-specs/`、`docs/exec-plans/tech-debt-tracker.md` 与 `docs/references/` 是否有漂移或过期条目，先删过期与重复内容，再归并新结论与 `memory/notes/`。
   - 检查 `docs/exec-plans/active/` 中已完结的计划：确认其 `Decision Log` 已逐条标注迁移落点或确认仅本次临时有效后，再移入 `docs/exec-plans/completed/`；未迁完的不归档。
4. Audit & Commit（六项门禁验收与原子提交）：
   - 将已吸收的 `memory/notes/` 笔记与早期 `dream-log` 条目移入 `memory/archive/`。
   - 运行 `python3 memory/dream_scan.py --audit` 并执行 `conda run -n agent-gate python -m pytest memory/tests -q`，确认六项门禁全清零：
     - `missing_required: []`
     - `broken: []`
     - `unindexed_decisions: []`
     - `unmigrated_completed_decisions: []`
     - `budget_and_style_violations: []`
     - `protected_sha256_prefix`（`AGENTS.md`）未变
   - 全部通过后更新 [memory/dream-log.md](../../../memory/dream-log.md) 的 `last_dream_at` 与本次摘要，并做一次原子 `git commit`（仅暂存受影响的文档、模块 `DECISIONS.md`、`memory/` 及相关技能，保留 `storage/data/` 等无关工作区目录）。
