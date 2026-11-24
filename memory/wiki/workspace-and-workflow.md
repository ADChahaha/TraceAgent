# 工作区目录地图与 Dreaming 维护规范

本页属 [workspace-index.md](workspace-index.md)，索引记忆系统结构、`dream_scan.py` 用法与本地开发测试入口（协作偏好见 [workspace-preferences.md](../preference/workspace-preferences.md)）。

## 记忆与控制面目录

| 路径 | 角色 | 说明 |
| --- | --- | --- |
| [AGENTS.md](../../AGENTS.md) | 持久规范（只读控制面） | TDD、文档同步、提交与记忆启动规则（日常与 Dreaming 不修改） |
| [memory.md](../../memory.md) | L0 顶层入口 | 全局锚点与 L1 路由（`<= 1500` 字符、禁直连 L2/L3） |
| `memory/preference/` | 用户偏好（L1 -> L2） | 经 [INDEX.md](../preference/INDEX.md) 路由通用协作与维护偏好 |
| `memory/wiki/` | 分层领域 Wiki | L1 `*-index.md` + L2 专题页 + L3 `experiments/` 或 `*-experiments.md` / `*-details.md` |
| `memory/notes/` | 轻量预判 Notes | 会中随手预判与踩坑；经 Dreaming 核验并入后归档至 `memory/archive/notes/` |
| `memory/tasks/` | Active Tasks | 仅放未完结或阻塞事项，完结后移入 `memory/archive/tasks/` |
| `memory/archive/` | 历史归档 | 完结任务、旧笔记与历史 `dream-log` |
| [dream-log.md](../dream-log.md) | Dreaming 台账 | 仅保留最近 2-3 次整理摘要及 `last_dream_at` 水位线 |
| [dream_scan.py](../dream_scan.py) | 扫描与门禁脚本 | 采集三端增量主会话、`--turn`/`--grep` 展开与 `--audit` 架构门禁 |
| [dreaming/SKILL.md](../../.agents/skills/dreaming/SKILL.md) | 手动整理 Skill | 分层按需 Dreaming 流程与 6 项程序化门禁 |

## 开发环境、测试与维护命令

- **Python 环境**：Conda 环境 `agent-gate`（Python 3.11），见 [agent/AGENTS.md](../../agent/AGENTS.md)。
- **安装与启动**：[scripts/install.sh](../../scripts/install.sh) 安装依赖并构建前端；[scripts/start.sh](../../scripts/start.sh) 一键启停 5 个本地服务。
- **常用测试**：
  - 记忆脚本：`conda run -n agent-gate python -m pytest memory/tests -q`
  - 脚本与 CI：`conda run -n agent-gate python -m pytest scripts/tests .github/tests -q`
  - 核心服务与前端测试口径见 [.github/workflows/ci.yml](../../.github/workflows/ci.yml)。
- **架构门禁**：`python3 memory/dream_scan.py --audit` 校验 6 项指标全清零（断链、分层预算、L0 越层链接、L2/L3 互链墙、BFS 不可达文件、受保护规则哈希）。
