# 记忆与 Dreaming 脚本设计

`memory/dream_scan.py` 是一个只读脚本，负责两件事：扫描本仓库在 Antigravity、Codex、Claude Code 三端的增量会话记录，以及检查 `memory/` 与 `memory.md` 的链接完整性和文件体量。

## 目录分工

- `memory.md` 是入口页，默认单文件字符提醒上限为 2500。
- `memory/preference/` 和 `memory/wiki/` 存放沉淀后的偏好与项目知识，按内容自然组织（内容少时可由 `memory.md` 直接链接，主题增多后再拆索引页），单页字符上限为 4500。
- `memory/notes/`、`memory/tasks/`、`memory/archive/`、`memory/dream-log.md` 参与断链检查，不计入活跃可达性图；`memory/docs/` 与 `memory/tests/` 属于工具自身文档与测试，不参与记忆检查。

## 输入与运行模式

- 默认以脚本上两级目录为 `repo_root`（支持 `--repo-root` 覆盖），增量水位线从 `memory/dream-log.md` 读取 `last_dream_at`，缺失或无效时回退到当前 UTC 前 48 小时，可用 `--since`、`--until`、`--all` 覆盖。
- 默认模式输出健康摘要、git 概览和增量主会话（USER 保留全文，ASSISTANT 截断并附 `--turn` 展开命令）；`--audit` 只输出健康摘要；`--grep` 按正则搜索轮次片段；`--session` 配合 `--turn`/`--offset`/`--tail`/`--all-turns` 查看指定会话原文。

## 三端会话匹配与过滤

- Antigravity：读 `~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl`，按 `repo_root` 路径或目录名匹配；USER 被截断或进入 `--grep`/`--session` 时按需读同目录 `transcript_full.jsonl`；按父日志中的 `conversationId`（兼容转义与未转义引号）及无用户输入轮次过滤子代理。
- Codex：读 `~/.codex/sessions/**/*.jsonl`，按 `session_meta.payload.cwd` 或文本中的仓库路径/目录名匹配，跳过系统注入文本和 `source.subagent`。
- Claude Code：读 `~/.claude/projects/*/*.jsonl`，将目录名转小写并把 `_` 转为 `-`（如 `agent_gate` 匹配 `agent-gate`），过滤 `isSidechain`、`agent-*`、meta 消息与中断占位。
- 仅传入 `--include-subagents` 或指定 `--session` 时包含子代理会话。

## 健康检查与降级

- 检查项：`broken`（相对/绝对路径与 `#anchor` 标题锚点）、`oversized_files`（超过入口或单页字符上限的活跃文件）、`unreachable_files`（从 `memory.md` 出发 BFS 不可达的活跃文件）、`protected_sha256_prefix`（`AGENTS.md` 的 SHA-256 前 12 位）。
- 异常与降级：无效 ISO 时间或正则直接报错退出；损坏的单条 JSONL 行跳过；非 git 目录降级为空 git 列表；缺少 `memory.md` 时入口计数记 0 并如实报告不可达文件。
