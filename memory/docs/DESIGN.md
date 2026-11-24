# 记忆与 Dreaming 脚本设计

`memory/dream_scan.py` 是一个只读脚本，做两件事：扫描本仓库在 Antigravity、Codex、Claude Code 三端的增量会话记录，以及校验 `memory/` 与 `memory.md` 的分层结构和链接完整性。

## 层级判定

- `L0`：`memory.md`（上限 1500 字 / 35 行 / 单行 200 字，只允许连向 L1）。
- `L1`：`memory/preference/INDEX.md` 和 `memory/wiki/*-index.md`（2200 / 45 / 220）。
- `L2`：`memory/preference/*.md` 和其他 `memory/wiki/**/*.md`（2600 / 65 / 260）。
- `L3`：`memory/wiki/experiments/*.md`、`*-experiments.md`、`*-details.md`（2400 / 55 / 260）。
- `notes/`、`tasks/`、`archive/`、`dream-log.md` 不计入预算和可达性图，但仍做断链校验；`memory/docs/` 与 `memory/tests/` 不参与记忆分层。

## 输入与模式

- 默认以脚本上两级目录为 `repo_root`（支持 `--repo-root` 覆盖），增量水位线从 `memory/dream-log.md` 读取 `last_dream_at`，缺失或无效时回退到当前 UTC 前 48 小时，可用 `--since`、`--until`、`--all` 覆盖。
- 默认模式输出架构体检、git 概览和增量主会话（USER 全文保留，ASSISTANT 截断并附 `--turn` 展开命令）；`--audit` 只做体检；`--grep` 按正则搜索轮次片段；`--session` 配合 `--turn`/`--offset`/`--tail`/`--all-turns` 查看指定会话原文。

## 三端会话匹配与过滤

- Antigravity：读 `~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl`，按 `repo_root` 路径或目录名匹配；USER 被截断或进入 `--grep`/`--session` 时按需读同目录 `transcript_full.jsonl`；按父日志中的 `conversationId`（兼容转义与未转义引号）及无用户输入轮次过滤子代理。
- Codex：读 `~/.codex/sessions/**/*.jsonl`，按 `session_meta.payload.cwd` 或文本中的仓库路径/目录名匹配，跳过系统注入文本和 `source.subagent`。
- Claude Code：读 `~/.claude/projects/*/*.jsonl`，将目录名转小写并把 `_` 转为 `-`（如 `agent_gate` 匹配 `agent-gate`），过滤 `isSidechain`、`agent-*`、meta 消息与中断占位。
- 仅传入 `--include-subagents` 或指定 `--session` 时包含子代理会话。

## 六项门禁与降级

- 检查项：`broken`（相对/绝对路径与 `#anchor` 锚点）、`budget_violations`、`layer_violations`（L0 直连 L2/L3）、`crosslink_walls`（L2/L3 单行内部 `.md` 链接超 5 个）、`unreachable_files`（从 `memory.md` 做 BFS）、`protected_sha256_prefix`（`AGENTS.md` 与 `agent/AGENTS.md` 的 SHA-256 前 12 位）。
- 异常与降级：无效 ISO 时间或正则直接报错退出；损坏的单条 JSONL 行跳过；非 git 目录降级为空 git 列表；缺少 `memory.md` 时 L0 记 0 并如实报告不可达文件。
