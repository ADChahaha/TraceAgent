# Dreaming 整理记录

last_dream_at: 2026-11-24T19:46:00+08:00

---

## 2026-11-24 首次增量 Dreaming（沉淀偏好与 backend 待修清单）

扫描 `2026-11-24T17:15:00+08:00` 后的 3 个历史会话并逐行核对源码：
- 偏好提纯：更新 [workspace-preferences.md](preference/workspace-preferences.md) 与 [INDEX.md](preference/INDEX.md)，去除对四层预算数字的复抄，明确"保留四层结构与六项门禁、但正文去规则腔与套话"及长文档分层规范。
- 知识与工作区瘦身：修剪 [workspace-and-workflow.md](wiki/workspace-and-workflow.md) 重复说明并补充 `storage/data/` 保留提示；在 [services.md](wiki/services.md) 同步文档拆分提示与 `backend` 待修清单入口。
- 待办沉淀：逐行核实 `backend/` 9 项未修缺陷（含 `:memory:` 启动崩溃、失败工具刷新误判、上传与活跃轮并发、取消收口与 SQLite 写事务放大等），单源落入 [backend-bugs-2026-11-24.md](tasks/backend-bugs-2026-11-24.md)。

## 2026-11-24 对齐 `japan_director` 四层记忆架构

按 `japan_director` 的四层按需记忆架构恢复 L0-L3 分层与六项程序化门禁：由 [memory.md](../memory.md)（L0）仅链接 [preference/INDEX.md](preference/INDEX.md)、[architecture-index.md](wiki/architecture-index.md) 和 [workspace-index.md](wiki/workspace-index.md) 三个 L1 索引，下钻至 [workspace-preferences.md](preference/workspace-preferences.md)、[services.md](wiki/services.md) 和 [workspace-and-workflow.md](wiki/workspace-and-workflow.md)，同步恢复 [dream_scan.py](dream_scan.py) 的层级预算、L0 越层检查与互链墙校验。

## 2026-11-24 初始化迁入

从 `japan_director` 迁入 `memory/dream_scan.py`、`.agents/skills/dreaming/SKILL.md` 与项目记忆目录，适配 `agent_gate` 仓库路径与三端会话扫描。
