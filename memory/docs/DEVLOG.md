# 记忆与 Dreaming 开发日志

## 2026-11-24

从 `~/Desktop/japan_director` 迁入 `memory/dream_scan.py`、`.agents/skills/dreaming/SKILL.md` 和项目内记忆目录，适配 `agent_gate` 路径与 Claude Code 连字符目录名（`agent-gate`），受保护文件哈希改为检查 `AGENTS.md` 和 `agent/AGENTS.md`。TDD 过程中修复了 Antigravity `transcript.jsonl` 内转义 `\"conversationId\"` 未被子代理正则匹配的问题。

同步将全仓 10 份过长设计与接口文档（`agent`、`file_extraction_agent`、`backend`、`document_processor`、`frontend`）拆分为索引页加同级子文件，并在 `AGENTS.md` 写入长文档分层与记忆启动规则。随后收薄了 `AGENTS.md`、`SKILL.md`、`memory/` 与各包文档中的重复规则和模板套话，删掉空壳索引页，活跃记忆压减至 5 份约 2.7k 字符。

验证：`conda run -n agent-gate python -m pytest memory/tests scripts/tests .github/tests -q` 全部 14 项通过；`python3 memory/dream_scan.py --audit` 6 项门禁清零；全仓拆分文档链接、体量和格式检查通过。
