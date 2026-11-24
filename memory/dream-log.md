# Dreaming 整理记录

last_dream_at: 2026-11-24T19:46:00+08:00

---

## 2026-11-24 合并去重至 OpenAI Harness 文档体系

将原四层记忆体系中与 OpenAI Harness 文档重叠的 `memory.md`、`memory/wiki/`、`memory/preference/` 与 `memory/tasks/` 全部迁并清理：
- 本地运行、测试与环境避坑提示迁入 [local-dev-and-testing.md](../docs/references/local-dev-and-testing.md)；写作与协作偏好并入 [core-beliefs.md](../docs/design-docs/core-beliefs.md)；9 项 `backend` 待修缺陷迁入 [backend-bugs-2026-11-24.md](../docs/exec-plans/active/backend-bugs-2026-11-24.md)。
- [dreaming/SKILL.md](../.agents/skills/dreaming/SKILL.md) 与 [dream_scan.py](dream_scan.py) 升级为面向 [ARCHITECTURE.md](../ARCHITECTURE.md)、`docs/` 与全仓模块 `DECISIONS.md` 的跨会话文档园艺与六项门禁审计工具。

## 2026-11-24 首次增量 Dreaming（沉淀偏好与 backend 待修清单）

扫描 `2026-11-24T17:15:00+08:00` 后的 3 个历史会话并逐行核对源码：提纯中文平实写作与长文档分层规范（现已合并入 [core-beliefs.md](../docs/design-docs/core-beliefs.md)），并核实 `backend/` 9 项待修缺陷（现跟踪于 [backend-bugs-2026-11-24.md](../docs/exec-plans/active/backend-bugs-2026-11-24.md)）。
