# 开发协作说明

Python 环境统一使用 Conda 的 `agent-gate`（Python 3.11）。各子包的设计与接口说明在对应的 `docs/DESIGN.md` 或 `docs/API.md`（已拆分时顺链接按需阅读）。

## 开发流程

- 动手前先读相关代码和最近的 `docs/DESIGN.md`；目标或改动范围不明确时先确认。
- 改动聚焦当前任务，不顺手修改无关代码；实现尽量直接简单，避免过早抽象。
- 行为变更先写失败测试，再用最小实现通过（纯文档、注释或无行为重命名除外）。
- 模块边界、流程或接口变化时，同步更新对应 `docs/DESIGN.md`、`DEVLOG.md` 和 `tests/docs/`；长文档按主题拆成索引页和子文件，`README` 与 `tests/docs/` 保持单文件。
- 代码、测试和文档验证通过后，检查 `git status` 与 `git diff`，按单一逻辑变更创建 commit，保留无关工作区修改。

## 沟通与写法

- 默认用中文交流，新增文档、注释和 docstring 用中文（标准英文术语除外）。
- 表达直接平实，避免破折号、弯引号和装饰性符号；注释只解释不直观的逻辑。
- 排查问题按实际读到的代码和现象说明位置与原因，原因不明时如实说明。

## 项目记忆

- 控制面与记忆面分离：本文件保存稳定开发规范，日常开发与 `dreaming` 不修改本文件。
- 活跃记忆按四层按需组织：L0 [memory.md](memory.md) 只放全局锚点与一级领域路由（不直连 L2/L3）；L1 索引（[preference/INDEX.md](memory/preference/INDEX.md) 与 `memory/wiki/*-index.md`）负责二级路由和域内总览；L2 存放专题知识与用户偏好；L3（`memory/wiki/experiments/*.md`、`*-experiments.md`、`*-details.md`）存放精简实证与明细摘要。
- 动态与归档目录：`memory/notes/` 放会中随手记下的轻量预判与踩坑（允许草稿态，留待 `dreaming` 核验后升格或归档），`memory/tasks/` 放未完成或阻塞事项，`memory/archive/` 放历史归档，[dream-log.md](memory/dream-log.md) 记录整理摘要与扫描水位线。
- 启动按需读取：新会话先读 [memory.md](memory.md) 并查看 `memory/notes/`，其余 `preference/`、`wiki/` 与 `tasks/` 按当前任务沿 L1 索引逐层打开，不整库全读；具体实现细节以源码和各包 `docs/DESIGN.md` 为准。
- 会中随手记与手动整理：对话中遇到跨会话会用到、不写就会丢的踩坑、阶段判断或偏好，顺手轻量记入 `memory/notes/` 或 `memory/preference/`，不打断主线且不抄源码流水账；跨会话回顾、纠偏与归并由用户显式触发 [dreaming](.agents/skills/dreaming/SKILL.md) 执行。
