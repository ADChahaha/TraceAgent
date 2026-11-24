---
name: dreaming
description: >-
  Manual memory consolidation skill for this repository. Use only when the user
  explicitly asks to run dreaming, consolidate or reflect on memory, or sync
  recent session transcripts and memory/notes/ into memory/wiki/,
  memory/preference/, and memory.md.
---

# Dreaming

仅在用户显式要求整理记忆或运行 dreaming 时执行。按下面四步回看增量会话、核对原件、修剪归并并验收。

## 层级与预算（由 `memory/dream_scan.py --audit` 检查）

| 层级 | 文件范围 | 上限（字符 / 行数 / 单行） |
| --- | --- | --- |
| L0 | [memory.md](../../../memory.md)（只连 L1 索引） | `1500 / 35 / 200` |
| L1 | [preference/INDEX.md](../../../memory/preference/INDEX.md)、`memory/wiki/*-index.md` | `2200 / 45 / 220` |
| L2 | `memory/preference/*.md`、其他 `memory/wiki/**/*.md` | `2600 / 65 / 260` |
| L3 | `memory/wiki/experiments/*.md`、`*-experiments.md`、`*-details.md` | `2400 / 55 / 260` |

写记忆时保持单源、平实简洁，不把源码或 `docs/DESIGN.md` 全文抄进记忆，不靠压成长单行躲行数限制，L2/L3 单行内部 `.md` 链接不超过 5 个。过程中不改 `AGENTS.md`、`agent/AGENTS.md`、业务代码或各包设计文档。

## 执行步骤

1. 先读 [memory.md](../../../memory.md)、[memory/dream-log.md](../../../memory/dream-log.md)、`memory/notes/` 和 `memory/tasks/`，不要一上来把所有 `wiki/` 和 `preference/` 全读完。
2. 在仓库根目录运行 `python3 memory/dream_scan.py` 获取上次水位线之后的增量主会话和结构体检结果；需要展开某条助手长回复或检索关键词时，用 `--session <id> --turn <N>` 或 `--grep <pattern>`，大积压用 `--order oldest --since/--until` 分批。
3. 只打开本次涉及的 L1/L2/L3 页面，对照源码、`git log` 或对应 `docs/DESIGN.md` 核实后再更新；先删过期和重复内容再写新结论，相对日期改写成 `YYYY-MM-DD`。只在影响全局入口或增删 L1 时改 `memory.md`。
4. 把已吸收的 `notes/`、完结任务和更早的 `dream-log` 条目移入 `memory/archive/`（`dream-log.md` 只留最近 2-3 次摘要），运行 `python3 memory/dream_scan.py --audit` 确认 `broken`、`budget_violations`、`layer_violations`、`crosslink_walls`、`unreachable_files` 全为空且 `protected_sha256_prefix` 未变，更新 `last_dream_at` 后只暂存 `memory/` 与 `memory.md` 提交。
