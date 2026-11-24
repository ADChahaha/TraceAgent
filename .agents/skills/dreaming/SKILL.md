---
name: dreaming
description: >-
  Manual memory consolidation skill for this repository. Use only when the user
  explicitly asks to run dreaming, consolidate or reflect on memory, or sync
  recent session transcripts and memory/notes/ into memory/wiki/,
  memory/preference/, and memory.md.
---

# Dreaming（分层按需记忆整理）

当用户显式要求执行 dreaming 或整理记忆时，按 Orient（按需） -> Gather Signal -> Consolidate & Prune（分层单源） -> Audit & Commit 对本仓库记忆做一次跨会话回顾、实证纠偏与结构瘦身。

## 核心架构：四层按需查找（L0 -> L1 -> L2 -> L3）

记忆维护遵守四层职责与唯一事实源（SSOT），不在顶层平铺细节或把长文压进单行：

| 层级 | 对应文件 | 职责边界 | 硬预算（由 `dream_scan.py` 审计） |
| --- | --- | --- | --- |
| L0 顶层入口 | [memory.md](../../../memory.md) | 仅存全局锚点、核心边界与 L1 路由表，不直连 L2/L3 细节页 | `<= 1500` 字符 / `<= 35` 行 / 单行 `<= 200` 字符 |
| L1 领域索引 | [preference/INDEX.md](../../../memory/preference/INDEX.md)、`memory/wiki/*-index.md` | 二级导航路由、域内总览与跨模块聚合；新增 L2 页挂到对应 L1 | `<= 2200` 字符 / `<= 45` 行 / 单行 `<= 220` 字符 |
| L2 专题与偏好 | `memory/preference/*.md`、其他 `memory/wiki/**/*.md` | 单主题决策、核心边界、偏好与一手锚点，不复抄源码或 `docs/DESIGN.md` 全文 | `<= 2600` 字符 / `<= 65` 行 / 单行 `<= 260` 字符 |
| L3 实证与明细 | `memory/wiki/experiments/*.md`、`*-experiments.md`、`*-details.md` | 评测口径、精简核心结果表、关键发现与原始实验脚本/报告锚点 | `<= 2400` 字符 / `<= 55` 行 / 单行 `<= 260` 字符 |

### 反膨胀约束

- 单源去重（SSOT）：每条事实只落 1 个权威页，其他页只留简短指针。
- 防止互链墙：跨模块共性聚合在对应 L1；L2/L3 只挂父页、配对页和少量强耦合直链，单行内部 `.md` 链接不超过 5 个。
- 不压成长单行躲行数检查：正常分点分段书写，逼近预算时先删过期与重复内容，再下沉细节回原件指针或按子主题拆分。
- 偏好去特例化：`memory/preference/` 只沉淀跨任务长期通用原则，绑死在单一服务的细节记入对应 `memory/wiki/` 子页。
- 不改控制面与业务文件：过程中不修改 `AGENTS.md`、业务代码或各包设计文档；查不到来源的内容如实标明待核。

## 执行流程（按需读取，不整库倾倒）

1. Orient（只读 L0 + 动态区）：
   - 先读 [memory.md](../../../memory.md)、[memory/dream-log.md](../../../memory/dream-log.md)（查看 `last_dream_at`）、`memory/notes/` 与 `memory/tasks/`。
   - 不开局全量读取所有 `memory/wiki/` 与 `memory/preference/` 文件；等步骤 2 明确受影响主题后，再沿 `L0 -> L1 -> L2/L3` 按需打开目标页。
2. Gather Signal（采集增量信号 + 架构体检）：
   - 在仓库根目录运行只读扫描脚本：`python3 memory/dream_scan.py`。
   - 需要展开某条助手长回复或检索关键词时，用 `--session <id> --turn <N>` 或 `--grep <pattern>`；积压较多时用 `--order oldest --since <T> --until <T>` 分批处理。
   - 若扫描报告存在既有结构违规，本次整理一并修剪归位。
3. Consolidate & Prune（先核对原件、再先剪后写）：
   - 按本次涉及的主题沿 L1 打开待改的 L2/L3 与偏好页，对照源码、`git log` 或各包 `docs/DESIGN.md` 核实事实后再更新。
   - 核查增量会话中用户拍板的决策是否已按三要素（做了什么决定、为什么这么选、排除了哪些备选方案）落盘：跨会话知识与偏好按单源补入 `memory/wiki/` 或 `memory/preference/`；若发现活动任务单或子包 `docs/DESIGN.md` 漏记，在整理摘要中标出（不改 `AGENTS.md` 和业务设计文档）。
   - 先清理过期、重复与超长单行，再按四层职责归并新结论、踩坑与 `memory/notes/`；相对日期统一改写为 `YYYY-MM-DD`。
   - 仅当变化影响全局锚点或增删 L1 索引时才改动 L0 `memory.md`。
4. Audit & Commit（程序化门禁验收）：
   - 将已吸收的 `memory/notes/`、完结任务及早期 `dream-log` 条目移入 `memory/archive/`（`dream-log.md` 只留最近 2-3 次摘要）。
   - 运行 `python3 memory/dream_scan.py --audit`，确认 6 项门禁全部清零且无异常：
     - `broken: []`
     - `budget_violations: []`
     - `layer_violations: []`
     - `crosslink_walls: []`
     - `unreachable_files: []`
     - `protected_sha256_prefix` 未变
   - 全部通过后更新 [memory/dream-log.md](../../../memory/dream-log.md) 的 `last_dream_at` 与本次摘要，并做一次原子 `git commit`（仅暂存 `memory/`、`memory.md` 及相关技能改动）。
