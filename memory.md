# 记忆总入口（L0）

更新时间：2026-11-24 | 规则见 [AGENTS.md](AGENTS.md) | 按需沿下方 L1 索引逐层下钻，不全量读取。

## 全局锚点与核心边界

- 项目定位：`agent_gate`（TraceAgent），基于只读文档虚拟仓库与数字引用的多轮文档 QA 工作台。
- 服务拆分：7 个顶层包（`agent_proto`、`storage`、`shared`、`document_service`、`agent`、`backend`、`frontend`）；`document_service` 与 `agent` 独立部署，只通过 S3 兼容 `storage` 交接会话资源，不互相 import。
- 本地运行：Python 统一使用 Conda 环境 `agent-gate`（Python 3.11）；默认单用户本地运行，数据库为 `backend/backend.sqlite3`，对象存储在 `storage/data`。
- 核实原则：改代码前先读目标文件、最近 `docs/DESIGN.md` 与对应模块 `DECISIONS.md`；先对齐验收标准再按"面向增加、谨慎修改"实现，即时记录决策三要素并在任务归档前迁出。

## 一级领域路由（L1，按需打开）

| 任务域 | L1 入口 | 涵盖主题 |
| --- | --- | --- |
| 用户偏好 | [preference/INDEX.md](memory/preference/INDEX.md) | 沟通写作习惯、验收驱动与决策记录、四层按需预算与 Dreaming 提交规范 |
| 架构与服务 | [architecture-index.md](memory/wiki/architecture-index.md) | 7 个顶层包职责边界、端口契约、调用约束与一手设计文档路由 |
| 工作区与维护 | [workspace-index.md](memory/wiki/workspace-index.md) | 仓库与记忆目录地图、本地启停与测试命令、`dream_scan.py` 用法与六项门禁 |

## 动态区与底层一手资料

- 活跃暂存：`memory/notes/`（会中预判与踩坑） / `docs/exec-plans/active/`（活动执行计划） / [dream-log.md](memory/dream-log.md)
- 一手架构与设计：[ARCHITECTURE.md](ARCHITECTURE.md) / [design-docs](docs/design-docs/index.md) / [README.md](README.md)
- 产品与技术债：[product-specs](docs/product-specs/index.md) / [tech-debt](docs/exec-plans/tech-debt-tracker.md)
