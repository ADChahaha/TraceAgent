# 记忆系统与 Dreaming 设计

本模块为 `agent_gate` 提供项目内四层按需记忆系统与离线 Dreaming 整理工具，用于在不把细节堆入控制面规则的前提下，跨会话保留长期决策、协作偏好与工作区定位。

## 实现思路

项目将规则控制面与项目记忆面分离：`AGENTS.md` 只保存稳定规范，日常会话和 Dreaming 都不修改；活跃记忆按 `L0 -> L1 -> L2 -> L3` 分层存放，新会话只读 L0 入口和 `memory/notes/`，其余按任务沿索引逐层下钻。离线整理通过 `.agents/skills/dreaming/SKILL.md` 驱动，并由只读脚本 `memory/dream_scan.py` 提供两类能力：跨客户端增量会话扫描（Antigravity / Codex / Claude Code）和六项程序化架构门禁审计。

```text
新会话启动
  -> 读 L0 memory.md 与 memory/notes/
  -> 按当前任务沿 L1 索引按需打开 L2 / L3 页面
  -> 一手实现细节回到代码与各包 docs/DESIGN.md 核实

手动触发 dreaming
  -> memory/dream_scan.py 采集三端增量主会话并输出结构体检
  -> 按需使用 --session / --turn / --grep 展开关键片段
  -> 先剪枝去重、核对仓内一手文件，再按四层职责归并并归档旧笔记
  -> memory/dream_scan.py --audit 校验 6 项门禁清零
  -> 更新 memory/dream-log.md 并提交记忆变更
```

## 目录与四层边界

| 层级 | 对应路径 | 职责边界 | 单文件预算 |
| --- | --- | --- | --- |
| L0 顶层入口 | `memory.md` | 仅存全局锚点、L1 路由表和动态区/一手资料入口，禁止直连 L2/L3 | `<= 1500` 字符 / `<= 35` 行 / 单行 `<= 200` 字符 |
| L1 领域索引 | `memory/preference/INDEX.md` 与 `memory/wiki/*-index.md` | 二级导航路由、跨模块状态总览与共享聚合 | `<= 2200` 字符 / `<= 45` 行 / 单行 `<= 220` 字符 |
| L2 专题与偏好 | `memory/preference/*.md` 与其他 `memory/wiki/**/*.md` | 单主题决策、边界、偏好与仓内锚点，不复抄 `docs/DESIGN.md` 全文 | `<= 2600` 字符 / `<= 65` 行 / 单行 `<= 260` 字符 |
| L3 实证与明细 | `memory/wiki/**/*-experiments.md`、`memory/wiki/**/*-details.md`、`memory/wiki/experiments/*.md` | 评测口径、精简结果摘要与原始实验脚本/报告锚点 | `<= 2400` 字符 / `<= 55` 行 / 单行 `<= 260` 字符 |

动态暂存与非分层目录不计入 L0-L3 预算和可达性图，但仍做断链校验：

- `memory/notes/`：会中轻量预判与踩坑草稿，待 Dreaming 核验吸收后移入 `memory/archive/notes/`。
- `memory/tasks/`：未完结或阻塞事项，完结后归档至 `memory/archive/tasks/`。
- `memory/dream-log.md`：仅留最近 2-3 次整理摘要与 `last_dream_at` 水位线，更早条目移入 `memory/archive/`。
- `memory/archive/`：历史归档。
- `memory/docs/` 与 `memory/tests/`：本模块的设计文档、开发日志与脚本测试，不参与活跃记忆分层审计。

## `dream_scan.py` 输入、校验、路由与输出

### 输入与默认定位

- 默认以脚本上两级目录作为 `repo_root`（可通过 `--repo-root` 覆盖），以用户主目录作为三端会话日志根目录（单元测试可传入隔离目录）。
- 增量扫描默认读取 `memory/dream-log.md` 中的 `last_dream_at` ISO 时间戳；缺失或格式无效时回退至当前 UTC 时间前 48 小时。支持 `--since`、`--until`、`--all` 覆盖。
- 支持四种执行模式：默认增量扫描（输出体检 + git 概览 + 增量会话摘要）、`--audit`（仅架构门禁审计）、`--grep`（按正则在会话轮次中检索紧凑片段）、`--session`（展开指定会话，配合 `--turn`、`--offset`、`--tail`、`--all-turns` 查看完整回复）。

### 三端会话匹配与子代理过滤

- Antigravity：扫描 `~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl`，匹配包含 `repo_root` 绝对路径或目录名的会话；当用户消息被截断或进入 `--grep` / `--session` 模式时按需读取同目录 `transcript_full.jsonl` 补全正文。通过解析父日志中的 `conversationId` 派生记录和无用户输入轮次过滤子代理会话。
- Codex：扫描 `~/.codex/sessions/**/*.jsonl`，匹配 `session_meta.payload.cwd` 位于 `repo_root` 下或正文中包含 `repo_root` / 目录名的会话；跳过系统注入前缀文本和 `source.subagent` 子会话。
- Claude Code：扫描 `~/.claude/projects/*/*.jsonl`，将 `repo_root.name` 转为小写及连字符形式（如 `agent_gate` -> `agent-gate`）匹配项目目录；过滤 `isSidechain`、`agent-*` 文件、meta 消息及中断占位。
- 仅在传入 `--include-subagents` 或显式指定 `--session` 时包含子代理会话。

### 六项架构门禁校验

1. `broken`：检查 `AGENTS.md`、`memory.md`、`memory/dream-log.md` 及 `wiki` / `preference` / `notes` / `tasks` / `archive` 下所有 Markdown 的相对路径、绝对路径与 `#anchor` 标题锚点。
2. `budget_violations`：按层校验总字符数、总行数和最长单行字符数。
3. `layer_violations`：校验 L0 `memory.md` 不得直连 L2/L3 内部记忆文件。
4. `crosslink_walls`：校验 L2/L3 单行内部 `.md` 链接数不超过 5 个，防止 $O(N^2)$ 互链墙。
5. `unreachable_files`：从 `memory.md` 出发做 BFS，确认所有活跃 L0-L3 文件均可达。
6. `protected_sha256_prefix`：输出受保护只读规则文件（`AGENTS.md`、`agent/AGENTS.md`）的 SHA-256 前 12 位，供 Dreaming 前后比对未误改控制面。

### 关键异常与降级

- 无效的 `--since` / `--until` ISO 时间戳或无效的 `--grep` 正则表达式直接抛出标准异常并终止，不静默忽略。
- 单条损坏的 JSONL 日志行会被跳过，不中断其余会话扫描。
- 在非 git 目录或缺少 `git` 命令时，扫描报告降级输出空 git 状态与提交列表；缺少 `memory.md` 时审计报告将 L0 记为 0 行/0 字符并如实报告不可达文件，不抛出 `FileNotFoundError`。
