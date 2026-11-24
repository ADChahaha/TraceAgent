# 工作区目录地图与维护入口

归属 [workspace-index.md](workspace-index.md)，记录记忆目录分工、本地运行测试入口与 Dreaming 维护命令（协作偏好见 [workspace-preferences.md](../preference/workspace-preferences.md)）。

## 控制面与记忆目录

| 路径 | 角色 | 说明 |
| --- | --- | --- |
| [AGENTS.md](../../AGENTS.md) | 只读控制面 | 开发流程、写法与启动规范，日常与 Dreaming 不修改 |
| [memory.md](../../memory.md) | L0 顶层入口 | 全局锚点与 L1 路由，不直连 L2/L3 |
| `memory/preference/` | 偏好区（L1 -> L2） | 经 [INDEX.md](../preference/INDEX.md) 路由跨会话通用偏好 |
| `memory/wiki/` | 分层 Wiki | L1 `*-index.md`、L2 专题页与 L3 实证/明细页 |
| `memory/notes/` | 临时笔记 | 会中预判、踩坑与跨模块阶段决策，Dreaming 吸收后归档 |
| `memory/tasks/` | 活动任务 | 施工暂存单（验收标准与决策记录）与阻塞事项，长期决策迁出后再归档至 `memory/archive/` |
| `memory/archive/` | 历史归档 | 完结任务、旧笔记与早期 `dream-log` |
| [dream-log.md](../dream-log.md) | 整理台账 | 保留最近 2-3 次摘要与 `last_dream_at` 水位线 |
| [dream_scan.py](../dream_scan.py) | 扫描与审计脚本 | 三端增量会话扫描、`--turn`/`--grep` 展开与 `--audit` 门禁 |
| [dreaming/SKILL.md](../../.agents/skills/dreaming/SKILL.md) | 手动整理技能 | 四阶段整理流程与六项门禁定义 |

## 本地运行、测试与环境提示

- 安装与启停：[scripts/install.sh](../../scripts/install.sh) 安装依赖并构建前端；[scripts/start.sh](../../scripts/start.sh) 一键启停 5 个本地服务；CI 见 [.github/workflows/ci.yml](../../.github/workflows/ci.yml)。
- 本地测试：
  - 记忆与脚本：`conda run -n agent-gate python -m pytest memory/tests scripts/tests .github/tests -q`
  - `agent` / `document_service` / `backend` 本地回环测试加 `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost` 避开系统代理。
  - 前端：`pnpm --dir frontend test --runInBand`。
- Hugging Face 公开模型下载若因本机 token 报 401，在 `.env` 设 `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`。
- 本地运行态目录 `storage/data/` 保持未跟踪，提交时不要误暂存。
- 架构审计：`python3 memory/dream_scan.py --audit`（详细规则见 [memory/docs/DESIGN.md](../docs/DESIGN.md)）。
