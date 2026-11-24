# `dream_scan.py` 扫描、匹配与六项门禁

本页属 [记忆系统与 Dreaming 设计](../DESIGN.md)，说明 `memory/dream_scan.py` 的输入校验、三端会话匹配、门禁规则与降级行为。

## 输入与执行模式

- 默认以脚本上两级目录作为 `repo_root`（可通过 `--repo-root` 覆盖），以用户主目录作为三端会话日志根目录（测试可注入隔离目录）。
- 增量扫描默认读取 `memory/dream-log.md` 的 `last_dream_at` ISO 时间戳；缺失或格式无效时回退至当前 UTC 时间前 48 小时。支持 `--since`、`--until`、`--all` 覆盖。
- 四种运行模式：默认增量扫描（体检 + git 概览 + 增量会话摘要）、`--audit`（仅架构门禁）、`--grep`（正则检索紧凑命中片段）、`--session`（展开指定会话，配合 `--turn`/`--offset`/`--tail`/`--all-turns` 查看完整回复）。

## 三端会话匹配与子代理过滤

- **Antigravity**：扫描 `~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl`，匹配包含 `repo_root` 绝对路径或目录名的会话；当 USER 文本被截断或进入 `--grep`/`--session` 时按需读取同目录 `transcript_full.jsonl`。通过解析父日志中的 `conversationId`（兼容转义与未转义格式）及无用户轮次过滤子代理。
- **Codex**：扫描 `~/.codex/sessions/**/*.jsonl`，匹配 `session_meta.payload.cwd` 位于 `repo_root` 下或正文中包含 `repo_root`/目录名的会话；跳过系统注入前缀文本和 `source.subagent` 子会话。
- **Claude Code**：扫描 `~/.claude/projects/*/*.jsonl`，将 `repo_root.name` 转为小写及连字符形式（`agent_gate` -> `agent-gate`）匹配项目目录；过滤 `isSidechain`、`agent-*`、meta 消息与中断占位。
- 仅传入 `--include-subagents` 或显式 `--session` 时包含子代理会话。

## 六项程序化架构门禁

1. `broken`：检查 `AGENTS.md`、`memory.md`、`memory/dream-log.md` 及 `wiki`/`preference`/`notes`/`tasks`/`archive` 下所有 Markdown 的相对/绝对路径与 `#anchor` 标题锚点。
2. `budget_violations`：按层校验总字符数、总行数和最长单行字符数。
3. `layer_violations`：校验 L0 `memory.md` 不得直连 L2/L3 内部记忆文件。
4. `crosslink_walls`：校验 L2/L3 单行内部 `.md` 链接数不超过 5 个。
5. `unreachable_files`：从 `memory.md` 出发做 BFS，确认所有活跃 L0-L3 文件均可达。
6. `protected_sha256_prefix`：输出受保护只读规则文件（`AGENTS.md`、`agent/AGENTS.md`）的 SHA-256 前 12 位。

## 异常与降级

- 无效的 `--since`/`--until` 时间戳或无效 `--grep` 正则直接抛出标准异常终止。
- 单条损坏的 JSONL 日志行自动跳过，不中断其余会话扫描。
- 非 git 目录或缺少 `git` 命令时降级输出空状态与提交列表；缺少 `memory.md` 时 L0 记为 0 行/0 字符并如实报告不可达文件。
