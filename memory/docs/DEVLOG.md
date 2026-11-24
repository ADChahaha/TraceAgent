# Dreaming 与文档门禁开发日志

## 2026-11-24（去重合并旧记忆至 OAI 文档，Dreaming 改为维护 OAI 文档体系）

依据用户拍板清理与 OpenAI Harness 重叠的四层静态记忆文件（详见 [DECISIONS.md](DECISIONS.md) 第 2 条）：
- 删除 `memory.md`、`memory/wiki/`、`memory/preference/`、`memory/tasks/` 及重复的 `memory/tests/test_docs_harness.py`；将本地运行与测试避坑提示迁入 [docs/references/local-dev-and-testing.md](../../docs/references/local-dev-and-testing.md)，协作与写作偏好并入 [docs/design-docs/core-beliefs.md](../../docs/design-docs/core-beliefs.md)。
- 改造 [dream_scan.py](../dream_scan.py) 的 `--audit` 为面向 `AGENTS.md`、`ARCHITECTURE.md`、`docs/` 与全仓模块 `DECISIONS.md` 的六项门禁（必需入口、断链与锚点、模块决策总目收录、归档计划决策迁出、`AGENTS.md` 预算与风格标点、控制面哈希）。
- 改写 [SKILL.md](../../.agents/skills/dreaming/SKILL.md) 与 [AGENTS.md](../../AGENTS.md)，使 `dreaming` 在核实源码后直接维护 `ARCHITECTURE.md`、`docs/` 与模块 `DECISIONS.md`（保持 `AGENTS.md` 与业务源码只读）。
- 同步更新 [DESIGN.md](DESIGN.md)、[dream-log.md](../dream-log.md)、[test_dream_scan.py](../tests/test_dream_scan.py) 与 [test_dream_scan.md](../tests/docs/test_dream_scan.md)。

## 2026-11-24（建立顶层 Harness 知识骨架与文档门禁测试）

按用户确认引入 OpenAI Harness 风格顶层结构，同时保留各包一手 `docs/DESIGN.md`、模块级 `DECISIONS.md` 与 `memory/` 四层记忆系统（详见 [DECISIONS.md](DECISIONS.md) 第 3 条）：
- 新建 [ARCHITECTURE.md](../../ARCHITECTURE.md)、[docs/design-docs/index.md](../../docs/design-docs/index.md)、[docs/design-docs/core-beliefs.md](../../docs/design-docs/core-beliefs.md)、[docs/product-specs/index.md](../../docs/product-specs/index.md)、[docs/product-specs/document-qa-workbench.md](../../docs/product-specs/document-qa-workbench.md) 与 [docs/exec-plans/tech-debt-tracker.md](../../docs/exec-plans/tech-debt-tracker.md)。
- 将 `memory/tasks/backend-bugs-2026-11-24.md` 迁入 `docs/exec-plans/active/backend-bugs-2026-11-24.md`（后于 2026-11-25 经确认不影响用户使用而撤下）并补齐验收标准与 `Decision Log` 槽位；`memory/tasks/` 保留空目录兼容 `dream_scan.py`。
- 同步更新 [AGENTS.md](../../AGENTS.md)、`memory.md`、偏好/工作区/架构记忆页、[dream-log.md](../dream-log.md) 与 [SKILL.md](../../.agents/skills/dreaming/SKILL.md)。
- 新增 `test_docs_harness.py` 与 `test_docs_harness.md`（后于同日合并进 [dream_scan.py](../dream_scan.py) 与 [test_dream_scan.py](../tests/test_dream_scan.py)），机械校验顶层知识文档链接、全仓 `DECISIONS.md` 总目收录及 `docs/exec-plans/completed/` 归档决策迁出标注。

## 2026-11-24（切换为验收驱动开发与模块级 `DECISIONS.md`）

依据用户拍板的协作流程调整（参考 OpenAI Harness engineering / ExecPlans 与 Anthropic 长运行 Harness / Evals 实践），同步更新 [AGENTS.md](../../AGENTS.md)、`memory.md`、`workspace-preferences.md`、`INDEX.md`、`workspace-and-workflow.md` 与 [SKILL.md](../../.agents/skills/dreaming/SKILL.md)，并将各包既有核心决策迁移到对应模块 `DECISIONS.md`（详见 [DECISIONS.md](DECISIONS.md)）：
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
