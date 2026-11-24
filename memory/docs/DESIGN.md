# Dreaming 扫描与文档门禁设计

`memory/dream_scan.py` 是一个只读脚本，负责两件事：扫描本仓库在 Antigravity、Codex、Claude Code 三端的增量会话记录，以及校验本仓库 OpenAI Harness 文档骨架、全仓模块 `DECISIONS.md` 与 `memory/` 动态区的完整性。

## 六项程序化门禁

1. `missing_required`：检查必需的顶层知识骨架存在（`AGENTS.md`、`ARCHITECTURE.md`、`docs/design-docs/index.md`、`docs/design-docs/core-beliefs.md`、`docs/product-specs/index.md`、`docs/exec-plans/tech-debt-tracker.md`、`memory/dream-log.md` 及 `docs/exec-plans/active/`、`docs/exec-plans/completed/`）。
2. `broken`：检查 `AGENTS.md`、`ARCHITECTURE.md`、`docs/**/*.md`、全仓模块 `DECISIONS.md`、`memory/dream-log.md` 及 `memory/notes/`、`memory/archive/` 下所有 Markdown 的相对路径、绝对路径与 `#anchor` 标题锚点。
3. `unindexed_decisions`：扫描全仓所有模块 `DECISIONS.md`（排除 `.git`、`node_modules`、`build`、`.next` 等产物目录），确认每一份都被 `docs/design-docs/index.md` 链接收录。
4. `unmigrated_completed_decisions`：检查 `docs/exec-plans/completed/*.md` 中的 `## Decision Log` 或 `## 决策记录` 列表项，确认每条均标明迁移去向（含 `->` 或 Markdown 链接）或确认为`临时有效`/`无需沉淀`。
5. `budget_and_style_violations`：校验 `AGENTS.md` 保持精简总目录（上限 80 行 / 4000 字符），且受检文档不含破折号或弯引号。
6. `protected_sha256_prefix`：输出受保护只读控制面（`AGENTS.md`）的 SHA-256 前 12 位，供 `dreaming` 核对控制面未被修改。

## 输入与运行模式

- 默认以脚本上两级目录为 `repo_root`（支持 `--repo-root` 覆盖），增量水位线从 `memory/dream-log.md` 读取 `last_dream_at`，缺失或无效时回退到当前 UTC 前 48 小时，可用 `--since`、`--until`、`--all` 覆盖。
- 默认模式输出六项门禁摘要、git 概览和增量主会话（USER 保留全文，ASSISTANT 截断并附 `--turn` 展开命令）；`--audit` 只输出六项门禁审计报告；`--grep` 按正则搜索轮次片段；`--session` 配合 `--turn`/`--offset`/`--tail`/`--all-turns` 查看指定会话原文。

## 三端会话匹配与过滤

- Antigravity：读 `~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl`，按 `repo_root` 路径或目录名匹配；USER 被截断或进入 `--grep`/`--session` 时按需读同目录 `transcript_full.jsonl`；按父日志中的 `conversationId`（兼容转义与未转义引号）及无用户输入轮次过滤子代理。
- Codex：读 `~/.codex/sessions/**/*.jsonl`，按 `session_meta.payload.cwd` 或文本中的仓库路径/目录名匹配，跳过系统注入文本和 `source.subagent`。
- Claude Code：读 `~/.claude/projects/*/*.jsonl`，将目录名转小写并把 `_` 转为 `-`（如 `agent_gate` 匹配 `agent-gate`），过滤 `isSidechain`、`agent-*`、meta 消息与中断占位。
- 仅传入 `--include-subagents` 或指定 `--session` 时包含子代理会话。

异常与降级：无效 ISO 时间或正则直接报错退出；损坏的单条 JSONL 行跳过；非 git 目录降级为空 git 列表；缺少 `docs/design-docs/index.md` 时将全部模块 `DECISIONS.md` 报告为未收录。

相关：[DECISIONS.md](DECISIONS.md) / [DEVLOG.md](DEVLOG.md)
