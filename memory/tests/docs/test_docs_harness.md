# 顶层 Harness 文档与模块决策门禁测试

对真实仓库顶层知识骨架和全仓 `DECISIONS.md` 做只读结构校验，并用临时目录验证归档执行计划的决策迁出门禁。

- `test_required_harness_files_and_agents_budget`：验证 `AGENTS.md`、`ARCHITECTURE.md`、`docs/design-docs/`、`docs/product-specs/` 与 `docs/exec-plans/` 关键入口存在，且 `AGENTS.md` 保持在 80 行以内的精简总目录体量。
- `test_harness_docs_and_decisions_links_and_style`：扫描 `AGENTS.md`、`ARCHITECTURE.md`、`docs/**/*.md` 与全仓 `DECISIONS.md`，确认本地相对链接全部有效且不含破折号或弯引号。
- `test_all_module_decisions_indexed_in_design_index`：确认全仓每份模块 `DECISIONS.md` 均已被 `docs/design-docs/index.md` 链接收录，防止新增模块决策脱钩。
- `test_completed_exec_plans_decision_graduation_gate`：在临时目录验证 `find_unmigrated_completed_decisions` 能放行已标明迁移落点或"临时有效"的归档决策、拦截未标注去向的条目，并校验真实仓库 `docs/exec-plans/completed/` 无违规。

运行：激活 `agent-gate` 后，在仓库根目录执行 `python -m pytest memory/tests -q`。
