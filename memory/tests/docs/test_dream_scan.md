# Dreaming 扫描与四层门禁测试

测试使用隔离临时目录模拟四层记忆目录与三端会话日志，不修改真实用户主目录或仓库数据；最后一项用例直接对当前仓库执行只读架构门禁检查。

- `load_dream_scan`：按路径动态加载 `memory/dream_scan.py`，脚本缺失时直接失败。
- `create_minimal_memory_repo`：在临时目录构造符合 L0 -> L1 -> L2 -> L3 结构的最小记忆目录，以及不参与分层预算与可达性图的 `notes/`、`tasks/`、`archive/`、`docs/`、`tests/` 目录。
- `test_classify_memory_tier_rules`：验证 L0（`memory.md`）、L1（`preference/INDEX.md`、`wiki/*-index.md`）、L2（偏好与专题页）、L3（`experiments/`、`*-experiments.md`、`*-details.md`）与非分层目录的判定规则。
- `test_check_memory_integrity_clean_repo`：验证干净四层仓库六项门禁全为空，返回正确的 `tier_totals`、`max_depth`、`total_active_files` 与 `AGENTS.md` SHA-256 前缀。
- `test_check_memory_integrity_detects_all_violations`：构造缺失文件、缺失中文标题锚点、`notes/` 内坏链、L0 越层直连 L2、L0 超长单行、L1 超行数预算、L2 单行互链墙（超过 5 个内部链接）和未连出的孤岛文件，确认全部逐项检出。
- `test_parse_last_dream_at_and_turn_spec`：验证 `dream-log.md` 水位线解析、文件缺失时的 48 小时 UTC 回退，以及 `--turn` 轮次区间与越界归一化。
- `test_cross_tool_transcript_scanners_filter_repo_and_subagents`：构造 Antigravity（含截断用户消息补全与转义子代理 `conversationId`）、Codex（`cwd` 与 `source.subagent`）和 Claude Code（连字符目录名 `-Users-tester-agent-gate` 与 `isSidechain`）日志，验证目标仓库匹配与子代理过滤。
- `test_cli_audit_grep_and_session_turn_modes`：通过子进程执行 `--audit`、`--grep` 与 `--session --turn`，验证 CLI 六项门禁摘要输出与未截断轮次展开。
- `test_real_repository_memory_audit_is_clean`：对实际 `agent_gate` 仓库执行 `check_memory_integrity`，确认断链、预算违规、越层链接、互链墙与不可达列表全为空，且具备 L0/L1/L2 活跃分层文件。

运行：激活 `agent-gate` 后，在仓库根目录执行 `python -m pytest memory/tests -q`。
