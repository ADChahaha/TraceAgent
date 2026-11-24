# 工作区、环境与维护索引（L1）

本页汇总仓库目录职责、本地运行环境、测试入口与记忆维护机制的二级路由（顶层入口见 [memory.md](../../memory.md)）。

## 页面路由

| 查找需求 | 目标页（L2） | 核心覆盖 |
| --- | --- | --- |
| 记忆目录分工、本地启停与测试命令、`dream_scan.py` 用法与门禁 | [workspace-and-workflow.md](workspace-and-workflow.md) | 四层目录地图、Conda 环境、代理与 HF 提示、测试入口与 6 项门禁 |

## 核心维护与脚本入口

- 记忆系统设计与日志：[memory/docs/DESIGN.md](../docs/DESIGN.md) / [memory/docs/DEVLOG.md](../docs/DEVLOG.md)
- 手动整理技能：[dreaming/SKILL.md](../../.agents/skills/dreaming/SKILL.md)
- 扫描与门禁脚本：[dream_scan.py](../dream_scan.py) / [dream-log.md](../dream-log.md)
- 本地启停与 CI：[scripts/install.sh](../../scripts/install.sh) / [scripts/start.sh](../../scripts/start.sh) / [.github/docs/DESIGN.md](../../.github/docs/DESIGN.md)
