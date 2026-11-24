# 记忆与 Dreaming 开发日志

## 2026-11-24

从 `~/Desktop/japan_director` 迁入 `memory/dream_scan.py`、`.agents/skills/dreaming/SKILL.md` 和项目内记忆目录，适配 `agent_gate` 路径与 Claude Code 连字符目录名（`agent-gate`）；TDD 过程中修复了 Antigravity `transcript.jsonl` 内转义 `\"conversationId\"` 未被子代理正则匹配的问题。

随后收薄并去规则化：
- 精简 `AGENTS.md`，去掉重复的"必须遵守 / 禁止事项 / 简要提醒"等强硬条文，删除过时且含断链的 `agent/AGENTS.md`。
- 按 TDD 简化 `memory/dream_scan.py` 检查逻辑：去掉 L0-L3 硬预算表、禁止 `memory.md` 直连主题页和单行链接数限制，只保留断链、孤岛文件、单文件体积上限和 `AGENTS.md` 哈希校验；删除两个空壳索引页（`memory/preference/INDEX.md`、`memory/wiki/project-index.md`），由 `memory.md` 直接链接偏好与服务页，并同步精简 `SKILL.md` 与 `memory/docs/DESIGN.md`。
- 清理各包设计与接口文档中的规则腔表述、机械目录表、混入前端设计文档的编码行数规定以及过密长行，保留原有分层结构和全部技术细节。

验证：`conda run -n agent-gate python -m pytest memory/tests scripts/tests .github/tests -q` 全部 13 项通过；`python3 memory/dream_scan.py --audit` 无断链、无超长或不可达文件；全仓 Markdown 相对链接与标点检查通过。
