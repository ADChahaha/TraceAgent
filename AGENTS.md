# 开发协作说明

本文件是仓库总入口与协作地图（Python 环境统一使用 Conda `agent-gate` / Python 3.11）。

## 仓库知识地图

- 顶层架构与依赖分层：[ARCHITECTURE.md](ARCHITECTURE.md)
- 设计总目与工程原则：[docs/design-docs/index.md](docs/design-docs/index.md) / [docs/design-docs/core-beliefs.md](docs/design-docs/core-beliefs.md)（各包一手设计在 `<pkg>/docs/DESIGN.md`，模块级决策在对应模块 `DECISIONS.md`）
- 产品规格（用户视角）：[docs/product-specs/index.md](docs/product-specs/index.md)
- 执行计划与技术债：`docs/exec-plans/active/`（进行中） / `docs/exec-plans/completed/`（已归档） / [tech-debt-tracker.md](docs/exec-plans/tech-debt-tracker.md)
- 跨会话记忆与整理：[memory.md](memory.md)（L0 路由入口） / [dreaming](.agents/skills/dreaming/SKILL.md)

## 开发流程

- 验收先行：动手前先读相关代码、对应产品规格、最近 `docs/DESIGN.md` 与目标模块 `DECISIONS.md`，把用户需求整理为具体、可观察的验收标准（含边界、非目标与验证方式）并确认后再实现。单轮明确的小改动在对话中简明确认；多文件、跨会话或存在方案取舍的任务，先在 `docs/exec-plans/active/` 建立执行计划单确认。
- 面向增加、围绕验收实现：遵循 [core-beliefs.md](docs/design-docs/core-beliefs.md)，改动聚焦当前任务，不顺手修改无关代码；新增能力或变化点优先通过新增独立模块或清晰扩展点承接，谨慎修改既有稳定逻辑（避免无意义的过度抽象）；与旧模块已有决策冲突时优先新增扩展而不是破坏旧契约。优先用面向外部行为的验收测试、集成测试或故障复现锁定结果，不机械要求对内部辅助函数逐一做微粒度测试先行。交付时逐条对照验收标准给出对应测试或实测证据；对跨服务、并发或高风险改动，完成后增加一次独立视角的只读核查（对照验收标准、diff 与运行结果挑刺）。
- 决策按模块即时落盘：对话中用户拍板的方案取舍、边界约束或否决项，在当轮或紧接的修改中立即记录，写清三项内容（做了什么决定、为什么这么选、排除了哪些备选方案）。模块决策就近写入对应包的对应模块 `DECISIONS.md`（独立子模块自带 `docs/` 时放 `<module>/docs/DECISIONS.md`，其余放 `<pkg>/<module>/DECISIONS.md`，并同步挂入对应包 `docs/DESIGN.md` 与 [docs/design-docs/index.md](docs/design-docs/index.md)）；跨包原则入 [core-beliefs.md](docs/design-docs/core-beliefs.md) 或 `memory/wiki/`，长期协作习惯入 `memory/preference/`，可验证的行为边界同步落入回归测试。`docs/exec-plans/active/` 中的 `Decision Log` 仅作施工暂存，移入 `docs/exec-plans/completed/` 前必须逐条迁出长期决策并标明去向（或确认仅本次临时有效），未迁完不归档。
- 同步文档与提交：模块边界、流程或接口变化时，同步更新对应 `docs/DESIGN.md`、`DECISIONS.md`、`DEVLOG.md`、`tests/docs/` 及 [docs/design-docs/index.md](docs/design-docs/index.md) 验证状态；长文档按主题拆成索引页和子文件，`README` 与 `tests/docs/` 保持单文件。验证通过后检查 `git status` 与 `git diff`，按单一逻辑变更创建 commit，保留无关工作区修改。

## 沟通与写法

- 默认用中文交流，新增文档、注释和 docstring 用中文（标准英文术语除外）。
- 表达直接平实，避免破折号、弯引号和装饰性符号；注释只解释不直观的逻辑。
- 排查问题按实际读到的代码和现象说明位置与原因，原因不明时如实说明。

## 项目记忆

- 控制面与记忆面分离：本文件保存稳定开发规范，日常开发与 `dreaming` 不修改本文件。
- 活跃记忆按四层按需组织：L0 [memory.md](memory.md) 只放全局锚点与一级领域路由（不直连 L2/L3）；L1 索引（[preference/INDEX.md](memory/preference/INDEX.md) 与 `memory/wiki/*-index.md`）负责二级路由和域内总览；L2 存放专题知识与用户偏好；L3（`memory/wiki/experiments/*.md`、`*-experiments.md`、`*-details.md`）存放精简实证与明细摘要。
- 动态与归档目录：`memory/notes/` 放会中轻量预判、踩坑与跨模块阶段判断（允许草稿态，留待 `dreaming` 核验后升格或归档），`memory/archive/` 放已吸收笔记与早期 `dream-log` 归档，[dream-log.md](memory/dream-log.md) 记录整理摘要与扫描水位线；工程执行计划统一走 `docs/exec-plans/`。
- 启动按需读取：新会话先读 [memory.md](memory.md) 并查看 `memory/notes/` 与 `docs/exec-plans/active/`，其余 `preference/`、`wiki/` 与 `docs/` 按当前任务沿索引逐层打开，不整库全读；具体实现细节以源码和一手设计文档为准。
- 会中随手记与手动整理：对话中遇到跨会话会用到、不写就会丢的决策、踩坑、阶段判断或偏好，当轮顺手轻量记入对应落点（模块 `DECISIONS.md`、`docs/exec-plans/active/`、`memory/notes/` 或 `memory/preference/`），不打断主线且不抄源码流水账；跨会话回顾、纠偏与归并由用户显式触发 [dreaming](.agents/skills/dreaming/SKILL.md) 执行。
