# Dreaming 扫描与 Harness 文档门禁测试

测试使用隔离临时目录模拟 OpenAI Harness 文档骨架、模块 `DECISIONS.md` 与三端会话日志，不修改真实用户主目录或仓库数据；最后一项用例直接对当前仓库执行只读六项门禁检查。

- `load_dream_scan`：按路径动态加载 `memory/dream_scan.py`，脚本缺失时直接失败。
- `create_minimal_harness_repo`：在临时目录构造包含 `AGENTS.md`、`ARCHITECTURE.md`、`docs/design-docs/`、`docs/product-specs/`、`docs/exec-plans/`、`pkg/mod/DECISIONS.md` 与 `memory/` 的最小仓库。
- `test_check_docs_integrity_clean_repo`：验证干净仓库六项门禁全为空，返回正确的模块决策清单、归档计划清单与 `AGENTS.md` SHA-256 前缀。
- `test_check_docs_integrity_detects_all_violations`：构造缺失必需入口、缺失文件与中文锚点、`memory/notes/` 坏链、未挂入 `docs/design-docs/index.md` 的孤岛 `DECISIONS.md`、归档计划中未标注去向的 `Decision Log`、`AGENTS.md` 超行数以及破折号/弯引号，确认全部逐项检出。
- `test_parse_last_dream_at_and_turn_spec`：验证 `dream-log.md` 水位线解析、文件缺失时的 48 小时 UTC 回退，以及 `--turn` 轮次区间与越界归一化。
- `test_cross_tool_transcript_scanners_filter_repo_and_subagents`：构造 Antigravity（含截断用户消息补全与转义子代理 `conversationId`）、Codex（`cwd` 与 `source.subagent`）和 Claude Code（连字符目录名 `-Users-tester-agent-gate` 与 `isSidechain`）日志，验证目标仓库匹配与子代理过滤。
- `test_cli_audit_grep_and_session_turn_modes`：通过子进程执行 `--audit`、`--grep` 与 `--session --turn`，验证 CLI 六项门禁摘要输出与未截断轮次展开。
- `test_real_repository_docs_audit_is_clean`：对实际 `agent_gate` 仓库执行 `check_docs_integrity`，确认六项门禁全为空且全部模块 `DECISIONS.md` 均已收录。

运行：激活 `agent-gate` 后，在仓库根目录执行 `python -m pytest memory/tests -q`。
