# 记忆与 Dreaming 开发日志

## 2026-11-24（切换为验收驱动开发与模块级 `DECISIONS.md`）

依据用户拍板的协作流程调整（参考 OpenAI Harness engineering / ExecPlans 与 Anthropic 长运行 Harness / Evals 实践），同步更新 [AGENTS.md](../../AGENTS.md)、[memory.md](../../memory.md)、[workspace-preferences.md](../preference/workspace-preferences.md)、[INDEX.md](../preference/INDEX.md)、[workspace-and-workflow.md](../wiki/workspace-and-workflow.md) 与 [SKILL.md](../../.agents/skills/dreaming/SKILL.md)，并将各包既有核心决策迁移到对应模块 `DECISIONS.md`（详见 [DECISIONS.md](DECISIONS.md)）：
- 决定：采用验收驱动开发与"面向增加、谨慎修改"实现原则；决策按三要素（做了什么决定、为什么这么选、排除了哪些备选方案）就近落入对应包对应模块的 `DECISIONS.md`（独立子模块放 `<module>/docs/DECISIONS.md`），并在对应包 `docs/DESIGN.md` 挂链接；`memory/tasks/` 归档前必须逐条迁出长期决策并标注去向。
- 原因：解决原微粒度 TDD 的自评偏差与 `memory/tasks/` 归档后遗忘问题，同时让代码与决策文档同步面向增量扩展。
- 排除：保留微粒度单测先行门禁；把决策留在归档任务单；另建全仓单一 `DECISIONS.md` 或平行 `docs/exec-plans/`、`docs/adr/` 目录。

## 2026-11-24（按 `japan_director` 恢复四层记忆架构）

对照 `~/Desktop/japan_director` 恢复完整的 L0-L3 四层按需记忆系统与六项程序化门禁，同时保留简洁平实的中文写法：
- 按 TDD 在 `memory/tests/test_dream_scan.py` 补回四层分类、分层体量预算、L0 越层链接、L2/L3 互链墙与真实仓库审计测试，随后在 `memory/dream_scan.py` 恢复 `classify_memory_tier`、`LAYER_BUDGETS`、`MAX_INLINE_INTERNAL_LINKS_L2_L3` 及六项门禁校验与 `--audit` 报告格式。
- 重建四层记忆目录：L0 `memory.md` 仅链接 3 个 L1 索引（`memory/preference/INDEX.md`、`memory/wiki/architecture-index.md`、`memory/wiki/workspace-index.md`），L1 路由至 3 个 L2 正文页（`memory/preference/workspace-preferences.md`、`memory/wiki/services.md`、`memory/wiki/workspace-and-workflow.md`），预留 L3 实证明细规则（`experiments/`、`*-experiments.md`、`*-details.md`）。
- 同步更新 `.agents/skills/dreaming/SKILL.md`、`AGENTS.md` 项目记忆说明、`memory/dream-log.md`、`memory/docs/DESIGN.md` 与 `memory/tests/docs/test_dream_scan.md`。

验证：`conda run -n agent-gate python -m pytest memory/tests scripts/tests .github/tests -q` 全部通过；`python3 memory/dream_scan.py --audit` 六项门禁全清零。

## 2026-11-24（初始化与精简）

从 `~/Desktop/japan_director` 迁入 `memory/dream_scan.py`、`.agents/skills/dreaming/SKILL.md` 和项目内记忆目录，适配 `agent_gate` 路径与 Claude Code 连字符目录名（`agent-gate`）；TDD 过程中修复了 Antigravity `transcript.jsonl` 内转义 `\"conversationId\"` 未被子代理正则匹配的问题。随后清理 `AGENTS.md` 与各包设计文档中的规则腔、冗余目录表及过时 `agent/AGENTS.md`。
