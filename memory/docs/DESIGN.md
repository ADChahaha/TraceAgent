# 记忆系统与 Dreaming 设计

本模块为 `agent_gate` 提供项目内四层按需记忆系统与离线 Dreaming 整理工具，用于在不把细节堆入控制面规则的前提下，跨会话保留长期决策、协作偏好与工作区定位。

项目将规则控制面与项目记忆面分离：`AGENTS.md` 只保存稳定规范，日常会话和 Dreaming 都不修改。
活跃记忆按 `L0 -> L1 -> L2 -> L3` 分层存放，新会话只读 L0 入口和 `memory/notes/`，其余按任务沿索引逐层下钻。离线整理通过 `.agents/skills/dreaming/SKILL.md` 驱动，由只读脚本 `memory/dream_scan.py` 提供跨端会话扫描与六项程序化架构门禁。

```text
新会话启动 -> 读 L0 memory.md 与 memory/notes/ -> 沿 L1 索引按需进 L2/L3 -> 细节回代码与各包 docs/DESIGN.md
手动 dreaming -> dream_scan.py 采集三端增量信号与体检 -> 先剪后写归并归档 -> --audit 六项清零 -> 更新 dream-log 并提交
```

## 目录与四层边界

| 层级 | 对应路径 | 职责边界 | 单文件预算 |
| --- | --- | --- | --- |
| L0 | `memory.md` | 全局锚点、L1 路由与动态区入口，禁止直连 L2/L3 | `<= 1500` 字 / `<= 35` 行 / 单行 `<= 200` |
| L1 | `memory/preference/INDEX.md`、`memory/wiki/*-index.md` | 二级导航路由、状态总览与共享聚合 | `<= 2200` 字 / `<= 45` 行 / 单行 `<= 220` |
| L2 | `memory/preference/*.md`、其他 `memory/wiki/**/*.md` | 单主题决策、偏好与仓内锚点，不复抄设计全文 | `<= 2600` 字 / `<= 65` 行 / 单行 `<= 260` |
| L3 | `memory/wiki/experiments/*.md`、`*-experiments.md`、`*-details.md` | 评测口径、精简结果摘要与原始脚本锚点 | `<= 2400` 字 / `<= 55` 行 / 单行 `<= 260` |

非分层目录（`notes/`、`tasks/`、`archive/`、`dream-log.md`、`docs/`、`tests/`）不计入 L0-L3 预算；其中前四类参与断链检查。

## 主题索引（按需打开）

| 主题 | 子文档 | 涵盖内容 |
| --- | --- | --- |
| 扫描器输入、三端匹配与六项门禁 | [design/scanner-and-audit.md](design/scanner-and-audit.md) | `dream_scan.py` 参数模式、三端日志匹配与子代理过滤、6 项门禁校验与异常降级 |

## 相关入口

- 整理技能：[SKILL.md](../../.agents/skills/dreaming/SKILL.md) / 开发日志：[DEVLOG.md](DEVLOG.md) / 测试说明：[test_dream_scan.md](../tests/docs/test_dream_scan.md)
