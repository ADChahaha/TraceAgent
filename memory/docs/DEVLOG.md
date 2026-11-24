# 记忆与 Dreaming 开发日志

## 2026-11-24（按 `japan_director` 恢复四层记忆架构）

对照 `~/Desktop/japan_director` 恢复完整的 L0-L3 四层按需记忆系统与六项程序化门禁，同时保留简洁平实的中文写法：
- 按 TDD 在 `memory/tests/test_dream_scan.py` 补回四层分类、分层体量预算、L0 越层链接、L2/L3 互链墙与真实仓库审计测试，随后在 `memory/dream_scan.py` 恢复 `classify_memory_tier`、`LAYER_BUDGETS`、`MAX_INLINE_INTERNAL_LINKS_L2_L3` 及六项门禁校验与 `--audit` 报告格式。
- 重建四层记忆目录：L0 `memory.md` 仅链接 3 个 L1 索引（`memory/preference/INDEX.md`、`memory/wiki/architecture-index.md`、`memory/wiki/workspace-index.md`），L1 路由至 3 个 L2 正文页（`memory/preference/workspace-preferences.md`、`memory/wiki/services.md`、`memory/wiki/workspace-and-workflow.md`），预留 L3 实证明细规则（`experiments/`、`*-experiments.md`、`*-details.md`）。
- 同步更新 `.agents/skills/dreaming/SKILL.md`、`AGENTS.md` 项目记忆说明、`memory/dream-log.md`、`memory/docs/DESIGN.md` 与 `memory/tests/docs/test_dream_scan.md`。

验证：`conda run -n agent-gate python -m pytest memory/tests scripts/tests .github/tests -q` 全部通过；`python3 memory/dream_scan.py --audit` 六项门禁全清零。

## 2026-11-24（初始化与精简）

从 `~/Desktop/japan_director` 迁入 `memory/dream_scan.py`、`.agents/skills/dreaming/SKILL.md` 和项目内记忆目录，适配 `agent_gate` 路径与 Claude Code 连字符目录名（`agent-gate`）；TDD 过程中修复了 Antigravity `transcript.jsonl` 内转义 `\"conversationId\"` 未被子代理正则匹配的问题。随后清理 `AGENTS.md` 与各包设计文档中的规则腔、冗余目录表及过时 `agent/AGENTS.md`。
