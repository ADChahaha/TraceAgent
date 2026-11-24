---
name: dreaming
description: >-
  Manual memory consolidation skill for this repository. Use only when the user
  explicitly asks to run dreaming, consolidate or reflect on memory, or sync
  recent session transcripts and memory/notes/ into memory/wiki/,
  memory/preference/, and memory.md.
---

# Dreaming

仅在用户明确要求整理记忆或运行 dreaming 时执行，用来回看近期会话、核对仓库现状并更新 `memory/`。过程中不改动 `AGENTS.md`、业务代码或各包设计文档。

## 整理步骤

1. 先读 [memory.md](../../../memory.md)、[memory/dream-log.md](../../../memory/dream-log.md)、`memory/notes/` 和 `memory/tasks/`，再按需要打开本次涉及的 `memory/wiki/` 或 `memory/preference/` 页面。
2. 在仓库根目录运行 `python3 memory/dream_scan.py` 获取上次水位线之后的增量会话；需要看某条回复全文或按关键词检索时，用 `--session <id> --turn <N>` 或 `--grep <pattern>`，积压较多时用 `--order oldest --since/--until` 分批处理。
3. 对照源码、`git log` 或各包 `docs/DESIGN.md` 核实事实后再更新记忆。先删过期和重复内容再写新结论，相对日期改写成 `YYYY-MM-DD`。保持单源简洁，不把源码或设计文档全文抄进记忆；页面变长或同主题多页时再按主题拆出索引与子页。
4. 将已吸收的 `notes/`、完结任务和更早的 `dream-log` 条目移入 `memory/archive/`（`dream-log.md` 只留最近 2-3 次摘要），运行 `python3 memory/dream_scan.py --audit` 确认无断链、无不可达或超长文件且 `AGENTS.md` 哈希未变，更新 `last_dream_at` 后只提交 `memory/` 和 `memory.md`。
