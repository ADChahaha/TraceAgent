# 记忆与 Dreaming 脚本设计

`memory/dream_scan.py` 是一个只读脚本，负责两件事：扫描本仓库在 Antigravity、Codex、Claude Code 三端的增量会话记录，以及校验 `memory/` 与 `memory.md` 的四层按需架构和链接完整性。

## 四层判定与预算

- `L0`：`memory.md`，上限 1500 字符 / 35 行 / 单行 200 字符，只允许连向 L1 索引页（或自身）。
- `L1`：`memory/preference/INDEX.md` 和 `memory/wiki/<name>-index.md`（路径深度为 2 且以 `-index.md` 结尾），上限 2200 字符 / 45 行 / 单行 220 字符。
- `L2`：`memory/preference/*.md`（除 `INDEX.md`）及其他 `memory/wiki/**/*.md`（除 L1 与 L3），上限 2600 字符 / 65 行 / 单行 260 字符。
- `L3`：`memory/wiki/experiments/*.md`、`memory/wiki/**/*-experiments.md`、`memory/wiki/**/*-details.md`，上限 2400 字符 / 55 行 / 单行 260 字符。
- `memory/notes/`、`memory/tasks/`、`memory/archive/`、`memory/dream-log.md` 参与断链校验，不计入 L0-L3 预算和可达性图；`memory/docs/` 与 `memory/tests/` 属于工具自身文档与测试，不参与记忆分层检查。

## 输入与运行模式

- 默认以脚本上两级目录为 `repo_root`（支持 `--repo-root` 覆盖），增量水位线从 `memory/dream-log.md` 读取 `last_dream_at`，缺失或无效时回退到当前 UTC 前 48 小时，可用 `--since`、`--until`、`--all` 覆盖。
- 默认模式输出架构体检摘要、git 概览和增量主会话（USER 保留全文，ASSISTANT 截断并附 `--turn` 展开命令）；`--audit` 只输出四层架构门禁审计报告；`--grep` 按正则搜索轮次片段；`--session` 配合 `--turn`/`--offset`/`--tail`/`--all-turns` 查看指定会话原文。

## 三端会话匹配与过滤

- Antigravity：读 `~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl`，按 `repo_root` 路径或目录名匹配；USER 被截断或进入 `--grep`/`--session` 时按需读同目录 `transcript_full.jsonl`；按父日志中的 `conversationId`（兼容转义与未转义引号）及无用户输入轮次过滤子代理。
- Codex：读 `~/.codex/sessions/**/*.jsonl`，按 `session_meta.payload.cwd` 或文本中的仓库路径/目录名匹配，跳过系统注入文本和 `source.subagent`。
- Claude Code：读 `~/.claude/projects/*/*.jsonl`，将目录名转小写并把 `_` 转为 `-`（如 `agent_gate` 匹配 `agent-gate`），过滤 `isSidechain`、`agent-*`、meta 消息与中断占位。
- 仅传入 `--include-subagents` 或指定 `--session` 时包含子代理会话。

## 六项门禁与降级

1. `broken`：检查 `AGENTS.md`、`memory.md`、`memory/dream-log.md` 及 `wiki` / `preference` / `notes` / `tasks` / `archive` 下所有 Markdown 的相对路径、绝对路径与 `#anchor` 标题锚点。
2. `budget_violations`：按 L0-L3 校验总字符数、总行数和最长单行字符数。
3. `layer_violations`：校验 L0 `memory.md` 不得直连 L2/L3 内部记忆文件。
4. `crosslink_walls`：校验 L2/L3 单行内部 `.md` 链接数不超过 5 个，防止 $O(N^2)$ 互链墙。
5. `unreachable_files`：从 `memory.md` 出发在活跃分层文件图上做 BFS，确认所有活跃 L0-L3 文件均可达并统计 `tier_totals` 与 `max_depth`。
6. `protected_sha256_prefix`：输出受保护只读规则文件（`AGENTS.md`）的 SHA-256 前 12 位，用于核对控制面未被修改。

异常与降级：无效 ISO 时间或正则直接报错退出；损坏的单条 JSONL 行跳过；非 git 目录降级为空 git 列表；缺少 `memory.md` 时 L0 记 0 并如实报告不可达文件。

相关：[DECISIONS.md](DECISIONS.md) / [DEVLOG.md](DEVLOG.md)
