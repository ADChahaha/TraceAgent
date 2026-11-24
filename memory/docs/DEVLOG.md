# 记忆与 Dreaming 开发日志

## 2026-11-24（切换为验收驱动开发与决策即时落盘）

依据用户拍板的协作流程调整（参考 OpenAI Harness engineering / ExecPlans 与 Anthropic 长运行 Harness / Evals 实践），同步更新 [AGENTS.md](../../AGENTS.md)、[memory.md](../../memory.md)、[workspace-preferences.md](../preference/workspace-preferences.md)、[INDEX.md](../preference/INDEX.md)、[workspace-and-workflow.md](../wiki/workspace-and-workflow.md) 与 [SKILL.md](../../.agents/skills/dreaming/SKILL.md)：
- 决定：将开发流程从"行为变更先写微粒度失败测试"改为"验收驱动开发"（先对齐用户可观察验收标准再实现，小改动对话确认、多文件/跨会话任务落 `memory/tasks/` 轻量任务单；高风险/并发/跨服务改动增加独立只读核查），并建立"决策即时落盘"规则（强制记录三要素：做了什么决定、为什么这么选、排除了哪些备选方案；Dreaming 兜底核查漏记）。
- 原因：原 TDD 规范容易变成 Agent 按内部实现细节自写单测并自评通过，偏离外部需求且难以覆盖集成边界；仅停留在聊天里的用户决策在跨会话后会丢失并引发反复返工。
- 排除的备选方案：排除"所有改动一律强制写任务单"（对单轮小改动过重）；排除新建顶层 `docs/exec-plans/` 或 `docs/adr/` 目录（与现有 `memory/tasks/` 及各子包 `docs/DESIGN.md` 重叠，违背单源去重原则）。

## 2026-11-24（按 `japan_director` 恢复四层记忆架构）

对照 `~/Desktop/japan_director` 恢复完整的 L0-L3 四层按需记忆系统与六项程序化门禁，同时保留简洁平实的中文写法：
- 按 TDD 在 `memory/tests/test_dream_scan.py` 补回四层分类、分层体量预算、L0 越层链接、L2/L3 互链墙与真实仓库审计测试，随后在 `memory/dream_scan.py` 恢复 `classify_memory_tier`、`LAYER_BUDGETS`、`MAX_INLINE_INTERNAL_LINKS_L2_L3` 及六项门禁校验与 `--audit` 报告格式。
- 重建四层记忆目录：L0 `memory.md` 仅链接 3 个 L1 索引（`memory/preference/INDEX.md`、`memory/wiki/architecture-index.md`、`memory/wiki/workspace-index.md`），L1 路由至 3 个 L2 正文页（`memory/preference/workspace-preferences.md`、`memory/wiki/services.md`、`memory/wiki/workspace-and-workflow.md`），预留 L3 实证明细规则（`experiments/`、`*-experiments.md`、`*-details.md`）。
- 同步更新 `.agents/skills/dreaming/SKILL.md`、`AGENTS.md` 项目记忆说明、`memory/dream-log.md`、`memory/docs/DESIGN.md` 与 `memory/tests/docs/test_dream_scan.md`。

验证：`conda run -n agent-gate python -m pytest memory/tests scripts/tests .github/tests -q` 全部通过；`python3 memory/dream_scan.py --audit` 六项门禁全清零。

## 2026-11-24（初始化与精简）

从 `~/Desktop/japan_director` 迁入 `memory/dream_scan.py`、`.agents/skills/dreaming/SKILL.md` 和项目内记忆目录，适配 `agent_gate` 路径与 Claude Code 连字符目录名（`agent-gate`）；TDD 过程中修复了 Antigravity `transcript.jsonl` 内转义 `\"conversationId\"` 未被子代理正则匹配的问题。随后清理 `AGENTS.md` 与各包设计文档中的规则腔、冗余目录表及过时 `agent/AGENTS.md`。
