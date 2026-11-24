# 记忆系统与 Dreaming 开发日志

## 2026-11-24

从 `~/Desktop/japan_director` 迁移项目内四层按需记忆系统（L0 `memory.md` -> L1 索引 -> L2 专题/偏好 -> L3 明细）与手动 `dreaming` 整理技能到 `agent_gate`，并完全适配当前仓库架构与规则约束。

主要改动：

- 在 `.agents/skills/dreaming/SKILL.md` 建立 `agent_gate` 专用 Dreaming 技能，保留四层体量预算、单源反膨胀、按需 Orient 与 6 项程序化门禁验收流程，去除原仓库的升学/CSV 业务口径。
- 按 TDD 实现 `memory/dream_scan.py`：默认动态解析仓库根目录并支持 `--repo-root` 覆盖；三端会话扫描适配 `agent_gate` 路径与 Claude Code 连字符项目名（`agent-gate`）；受保护文件哈希检查对象改为只读控制面 `AGENTS.md` 和 `agent/AGENTS.md`。红灯阶段单元测试同时暴露并修复了 Antigravity `transcript.jsonl` 中嵌套转义 `\"conversationId\"` 未被子代理正则识别的问题。
- 初始化 `memory.md`、`memory/dream-log.md`、`memory/preference/`、`memory/wiki/`（`architecture-index.md`、`services-overview.md`、`workspace-index.md`、`workspace-and-workflow.md`）与 `notes/`、`tasks/`、`archive/` 目录，并在 `AGENTS.md` 第 7 节接入控制面与记忆面分工及启动按需读取规范。
- 同步编写 `memory/docs/DESIGN.md`、`memory/tests/test_dream_scan.py` 与 `memory/tests/docs/test_dream_scan.md`。

验证：在 `agent-gate` 环境中执行 `python -m pytest memory/tests -q` 全部 7 项通过；执行 `python3 memory/dream_scan.py --audit` 确认 6 项门禁清零；执行 `python3 memory/dream_scan.py --all --max-sessions 3` 验证三端真实日志扫描正常；并回归运行 `scripts/tests` 与 `.github/tests` 确认无影响。

### 存量设计与接口文档分层重构

按确认范围将全仓 10 份过长设计与接口文档（`agent/docs/DESIGN.md`、`agent/docs/API.md`、`agent/service/file_extraction_agent/docs/DESIGN.md`、`tools.md`、`backend/docs/DESIGN.md`、`SESSION_MANAGER.md`、`table.md`、`API.md`、`document_service/document_processor/docs/DESIGN.md`、`frontend/docs/DESIGN.md`）及 `memory/docs/DESIGN.md` 原地拆分为"轻量总览索引页 + 同级主题子文件"，保留全部原入口路径不断链，修正了 `file_extraction_agent/docs/DESIGN.md` 中失效的 `document_resources` 相对链接和 `document_processor` 路径笔误，并在 `memory/wiki/docs-map.md` 与 `architecture-index.md` 建立按需路由。

验证：全量链接与单文件体量预算脚本检查 0 断链、0 违禁标点、索引/子文件体量合规；`python3 memory/dream_scan.py --audit` 6 项门禁清零；`memory/tests`、`scripts/tests` 与 `.github/tests` 全部通过。
