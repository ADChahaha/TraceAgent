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

- 跨会话背景和偏好放在 [memory.md](memory.md) 和 `memory/`：`preference/` 放协作偏好，`wiki/` 放项目知识，`notes/` 顺手记容易忘的踩坑或判断，`tasks/` 放未完事项，`archive/` 放归档。
- 新会话先看 [memory.md](memory.md) 和 `memory/notes/`，其余按需打开，具体实现以源码和 `docs/DESIGN.md` 为准。
- 平时有值得留下的坑或偏好顺手记进 `notes/` 或 `preference/`，需要整理时由用户触发 [dreaming](.agents/skills/dreaming/SKILL.md)。日常开发与 `dreaming` 不修改本文件。
