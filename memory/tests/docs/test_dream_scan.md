# Dreaming 扫描与检查测试

测试使用隔离临时目录模拟记忆目录与三端会话日志，不修改真实用户主目录或仓库数据；最后一项用例直接对当前仓库执行只读健康检查。

- `load_dream_scan`：按路径动态加载 `memory/dream_scan.py`，脚本缺失时直接失败。
- `create_minimal_memory_repo`：在临时目录构造直接从 `memory.md` 链接到偏好和 wiki 页的最小记忆目录，以及不参与可达性图的辅助目录。
- `test_check_memory_integrity_clean_repo_allows_direct_links`：验证 `memory.md` 直接链接主题页可通过检查，返回正确的最大深度、活跃文件计数与 `AGENTS.md` SHA-256 前缀，不再产生分层或互链墙字段。
- `test_check_memory_integrity_detects_broken_oversized_and_unreachable`：构造缺失文件、缺失中文标题锚点、`notes/` 内坏链、超长入口文件和未连出的孤岛文件，确认逐项检出，同时单行多个链接不报错。
- `test_parse_last_dream_at_and_turn_spec`：验证 `dream-log.md` 水位线解析、文件缺失时的 48 小时 UTC 回退，以及 `--turn` 轮次区间与越界归一化。
- `test_cross_tool_transcript_scanners_filter_repo_and_subagents`：构造 Antigravity（含截断用户消息补全与转义子代理 `conversationId`）、Codex（`cwd` 与 `source.subagent`）和 Claude Code（连字符目录名 `-Users-tester-agent-gate` 与 `isSidechain`）日志，验证目标仓库匹配与子代理过滤。
- `test_cli_audit_grep_and_session_turn_modes`：通过子进程执行 `--audit`、`--grep` 与 `--session --turn`，验证 CLI 输出与未截断轮次展开。
- `test_real_repository_memory_audit_is_clean`：对实际 `agent_gate` 仓库执行 `check_memory_integrity`，确认断链、超长与不可达列表全为空。

运行：激活 `agent-gate` 后，在仓库根目录执行 `python -m pytest memory/tests -q`。
