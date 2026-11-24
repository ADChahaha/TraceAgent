---
name: dreaming
description: >-
  Manual memory consolidation skill for this repository. Use only when the user
  explicitly asks to run dreaming, consolidate or reflect on memory, or sync
  recent session transcripts and memory/notes/ into memory/wiki/,
  memory/preference/, and memory.md.
---

# Dreaming（分层按需记忆整理）

当用户显式要求执行 dreaming 或整理记忆时，按 **Orient（按需） -> Gather Signal -> Consolidate & Prune（分层单源） -> Audit & Commit** 对本仓库记忆做一次跨会话回顾、实证纠偏与结构瘦身。

## 核心架构：四层按需查找（L0 -> L1 -> L2 -> L3）

本仓库记忆严禁平铺堆积行数或把长文塞进单行，所有维护必须遵守四层职责与唯一事实源（SSOT）：

| 层级 | 对应文件 | 职责边界（严禁越层） | 硬预算（由 `dream_scan.py` 审计） |
| --- | --- | --- | --- |
| **L0 顶层入口** | [memory.md](../../../memory.md) | 仅存全局锚点、一句话状态与 L1 入口路由；**严禁直连 L2/L3 细节页**或堆单模块实现细节 | `<= 1500` 字符 / `<= 35` 行 / 单行 `<= 200` 字符 |
| **L1 领域索引** | [preference/INDEX.md](../../../memory/preference/INDEX.md) / [architecture-index.md](../../../memory/wiki/architecture-index.md) / [workspace-index.md](../../../memory/wiki/workspace-index.md) 及新增 `memory/wiki/*-index.md` | 二级导航路由、跨模块状态总览与共享聚合；新增 L2 页只挂到对应 L1 | `<= 2200` 字符 / `<= 45` 行 / 单行 `<= 220` 字符 |
| **L2 专题与偏好** | `memory/preference/*.md` 与其他 `memory/wiki/**/*.md` | 单主题决策、核心边界、一手锚点与待办；**不复抄源码或各包 `docs/DESIGN.md` 全文** | `<= 2600` 字符 / `<= 65` 行 / 单行 `<= 260` 字符 |
| **L3 实证与明细** | `memory/wiki/experiments/*.md`、`memory/wiki/**/*-experiments.md`、`memory/wiki/**/*-details.md` | 评测口径、精简核心结果表、关键发现与原始脚本/报告锚点；**不复抄逐轮日志流水账** | `<= 2400` 字符 / `<= 55` 行 / 单行 `<= 260` 字符 |

### 反膨胀硬约束

- **禁止重复镜像（SSOT）**：每条事实只落 1 个权威页，其他页只留简短指针（如服务边界归 `services-overview.md` 及各包 `docs/DESIGN.md`，协作习惯归 `memory/preference/`，实验结果归 L3 页）。
- **禁止 O(N^2) 互链墙**：跨模块共性主题统一聚合在对应 L1 索引；L2/L3 页只挂父页、自身配对页与 1-2 个强耦合直链，**单行内部 `.md` 链接不得超过 5 个**。
- **禁止压成长单行躲行数检查**：正常分点/分段书写，单行严守各层字符上限；文件逼近上限时，先删过期过程与重复复述，再下沉细节回仓内原件指针或按子主题拆分。
- **偏好去特例化**：`memory/preference/` 只沉淀跨任务通用原则，绑死在单一模块或单次排查的细节留回对应 L2/L3 页。
- **不动规则与业务代码**：Dreaming 过程不修改 `AGENTS.md`、`agent/AGENTS.md`、业务源码或各包 `docs/DESIGN.md`，不自动发起新开发任务；查不到一手证据的内容如实标明待核。

## 执行流程（按需读取，不整库倾倒）

1. **Orient（只读 L0 + 动态区）**：
   - 先读 [memory.md](../../../memory.md)、[memory/dream-log.md](../../../memory/dream-log.md)（看 `last_dream_at`）、`memory/notes/` 与 `memory/tasks/`。
   - **不要开局全量读取所有 `memory/wiki/` 与 `memory/preference/` 文件**；等步骤 2 明确受影响主题后，再沿 `L0 -> L1 -> L2/L3` 按需打开对应页面。
2. **Gather Signal（采集增量信号 + 架构体检）**：
   - 在仓库根目录运行只读扫描脚本：
     ```bash
     python3 memory/dream_scan.py
     ```
   - 脚本完整保留主会话每条用户原话，并截断助手回复留 `--turn` / `--grep` 展开口子（大积压可用 `--order oldest --since <T> --until <T>` 分批）；同时自动输出 `budget_violations`、`layer_violations`、`crosslink_walls`、`unreachable_files` 与 `broken`。
   - 若扫描显示任何既有结构违规，本次 Dreaming 须一并修剪归位。
3. **Consolidate & Prune（先核对原件、再先剪后写）**：
   - 按本次涉及的主题/模块，沿 L1 索引仅打开需修改的 L2/L3 与偏好页，并局部回查代码、`git log` 或对应 `docs/DESIGN.md` / `DEVLOG.md` 纠偏。
   - 先清理过期、重复与超长单行，再按四层职责归并新决定、踩坑、纠偏与 `memory/notes/`；把相对日期统一写为 `YYYY-MM-DD`。
   - 仅当状态变化影响全局摘要或新增/删除 L1 入口时，才同步微调 L0 [memory.md](../../../memory.md)。
4. **Audit & Commit（程序化门禁验收）**：
   - 将已吸收的 `memory/notes/`、已完结任务及早期 `dream-log` 条目移进 `memory/archive/`（`memory/dream-log.md` 仅留最近 2-3 次精炼摘要）。
   - 运行快速架构门禁校验：
     ```bash
     python3 memory/dream_scan.py --audit
     ```
   - 确认 6 项门禁全部清零且无异常：
     - `broken: []`
     - `budget_violations: []`
     - `layer_violations: []`
     - `crosslink_walls: []`
     - `unreachable_files: []`
     - `protected_sha256_prefix` 未变
   - 全部通过后更新 [memory/dream-log.md](../../../memory/dream-log.md) 的 `last_dream_at` 与本次摘要，并做一次 `git commit`（仅暂存 `memory/`、`memory.md` 及相关技能改动，不混入未完成业务文件）。
