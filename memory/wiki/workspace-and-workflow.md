# 工作区目录地图与维护规范

本页属 [workspace-index.md](workspace-index.md)，记录记忆四层目录分工、本地开发测试入口与 Dreaming 维护命令（协作偏好见 [workspace-preferences.md](../preference/workspace-preferences.md)）。

## 控制面与记忆目录

| 路径 | 角色 | 说明 |
| --- | --- | --- |
| [AGENTS.md](../../AGENTS.md) | 持久规范（只读控制面） | 开发流程、写作规范与记忆启动规则，日常与 Dreaming 不修改 |
| [memory.md](../../memory.md) | L0 顶层入口 | 全局锚点与 L1 路由（`<= 1500` 字符、禁直连 L2/L3） |
| `memory/preference/` | 用户偏好（L1 -> L2） | 经 [INDEX.md](../preference/INDEX.md) 路由通用协作与维护偏好 |
| `memory/wiki/` | 分层领域 Wiki | L1 `*-index.md` + L2 专题页 + L3 `experiments/`、`*-experiments.md`、`*-details.md` |
| `memory/notes/` | 会中 Salient 笔记 | 轻量预判与踩坑；经 Dreaming 核验并入后归档至 `memory/archive/` |
| `memory/tasks/` | 活动任务 | 仅放未完结或阻塞事项，完结后归档 |
| `memory/archive/` | 历史归档 | 完结任务、旧笔记与历史 `dream-log` |
| [dream-log.md](../dream-log.md) | Dreaming 台账 | 保留最近 2-3 次整理摘要及 `last_dream_at` 水位线 |
| [dream_scan.py](../dream_scan.py) | 扫描与门禁脚本 | 采集三端增量主会话、`--turn`/`--grep` 展开与 `--audit` 六项门禁 |
| [dreaming/SKILL.md](../../.agents/skills/dreaming/SKILL.md) | 手动整理 Skill | 四层按需整理流程与六项程序化门禁 |

## 本地运行、测试与环境提示

- 安装与启停：[scripts/install.sh](../../scripts/install.sh) 安装依赖并构建前端；[scripts/start.sh](../../scripts/start.sh) 一键启停 5 个本地服务。
- CI 口径：[.github/workflows/ci.yml](../../.github/workflows/ci.yml) / [.github/docs/DESIGN.md](../../.github/docs/DESIGN.md)。
- 本地测试：
  - 记忆与脚本：`conda run -n agent-gate python -m pytest memory/tests scripts/tests .github/tests -q`
  - `agent` / `document_service` / `backend` 本地回环测试加 `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost` 避开系统代理。
  - 前端：`pnpm --dir frontend test --runInBand`。
- Hugging Face 公开模型下载若因本机 token 报 401，在 `.env` 设 `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`。
- 架构门禁：`python3 memory/dream_scan.py --audit` 校验 6 项指标清零（断链、分层预算、L0 越层链接、L2/L3 互链墙、BFS 不可达、受保护规则哈希）。
