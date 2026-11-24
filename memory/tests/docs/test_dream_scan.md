# Dreaming 扫描与架构门禁测试

测试使用隔离临时目录模拟记忆层级与三端会话日志，不修改真实用户主目录或仓库数据；最后一项用例直接对当前仓库执行只读架构门禁检查。

- `load_dream_scan`：按路径动态加载 `memory/dream_scan.py`，脚本缺失时直接失败。
- `create_minimal_memory_repo`：在临时目录构造符合 L0 -> L1 -> L2 -> L3 规范的最小记忆仓库与 `AGENTS.md`。
- `test_classify_memory_tier_rules`：校验 `classify_memory_tier` 对 L0、L1、L2、L3 及非分层目录（`notes`、`tasks`、`archive`、`docs`、`tests`、`dream-log.md`）的分类边界。
- `test_check_memory_integrity_clean_repo`：验证合法四层仓库通过全部 6 项门禁，且返回正确的最大深度、活跃文件计数与 `AGENTS.md` SHA-256 前缀。
- `test_check_memory_integrity_detects_all_violations`：构造断链、缺失中文标题锚点、L0 越层直连、超长单行、L2 互链墙和不可达孤岛文件，确认门禁逐项检出。
- `test_parse_last_dream_at_and_turn_spec`：验证 `dream-log.md` 水位线解析、文件缺失时的 48 小时 UTC 回退，以及 `--turn` 轮次区间/越界归一化。
- `test_cross_tool_transcript_scanners_filter_repo_and_subagents`：构造 Antigravity（含截断用户消息补全与转义子代理 `conversationId`）、Codex（`cwd` 与 `source.subagent`）和 Claude Code（连字符目录名 `-Users-tester-agent-gate` 与 `isSidechain`）日志，验证目标仓库匹配与子代理过滤。
- `test_cli_audit_grep_and_session_turn_modes`：通过子进程执行 `--audit`、`--grep` 与 `--session --turn`，验证 CLI 输出和未截断轮次展开。
- `test_real_repository_memory_audit_is_clean`：对实际 `agent_gate` 仓库执行 `check_memory_integrity`，确认迁移后的记忆体系 6 项门禁全清零。

运行：激活 `agent-gate` 后，在仓库根目录执行 `python -m pytest memory/tests -q`。
