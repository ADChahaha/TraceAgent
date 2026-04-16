# AGENT Operating Guide

本文件定义在本仓库中工作的统一协作约定（面向人和 LLM）。

## 0. 适用范围

- 作用域：仓库根目录下所有 service（如 `agent/`、`backend/`、`frontend/`）
- 目标：确保跨会话、跨模型切换时上下文不断裂

## 1. 开始任何任务前（必须）

1. 先定位你要修改的 service。
2. 先阅读该 service 下的 `CONTEXT.md`。
3. 如果该 service 暂无 `CONTEXT.md`，先创建再开始开发。

示例：
- 修改 `agent/`：先读 `agent/CONTEXT.md`
- 修改 `backend/`：先读 `backend/CONTEXT.md`（若不存在则先创建）
- 修改 `frontend/`：先读 `frontend/CONTEXT.md`（若不存在则先创建）

## 2. 完成任务后（必须）

每次完成一轮可交付改动（代码、文档、测试、配置）后，必须更新对应 service 的 `CONTEXT.md`，至少包含：

- 项目总览（当前阶段、核心模块、主链路）
- 本次目标与范围
- 已完成变更（文件/模块级）
- 测试与验证结果
- 当前未解决问题/风险
- 下一步建议
- 相关 commit（若已提交）

其中“项目总览”要求：
- 放在 `CONTEXT.md` 前部（建议在第 1 节）
- 保持短小（建议 5-12 行），只保留当前有效信息
- 当阶段变化时必须同步更新，避免与正文状态不一致

## 3. 更新粒度要求

- 小改动：可简短增量记录（几行）
- 中/大改动：必须写清“决策原因 + 影响范围 + 回滚点”
- 避免空泛描述，优先写可执行信息（命令、路径、状态）

## 3.1 TDD 过程中的 CONTEXT 同步（必须）

- 如果采用 TDD（如 `red -> green -> refactor`）推进功能，不要等到全部完成后才一次性更新 `CONTEXT.md`
- 至少在以下节点同步对应 service 的 `CONTEXT.md`：
  - `red`：新增失败测试后，记录目标行为、失败点、当前阶段
  - `green`：实现通过后，记录实现方案、验证结果、剩余风险
  - `refactor`（若有）：记录重构原因、影响范围、回滚点
- 如果 TDD 期间已经产生原子提交，`CONTEXT.md` 应补充这些 commit，保证接手者能看出当前处于哪一阶段

## 3.2 CONTEXT.md 长度控制（必须）

- 更新 `CONTEXT.md` 时保持简洁，优先保留“当前可执行信息”，避免长篇背景复述。
- 当 `CONTEXT.md` 明显变长、影响快速阅读时，必须先压缩再追加：
  - 把已完成且稳定的历史内容合并为短摘要（3-8 行）
  - 保留关键决策、当前状态、阻塞点、下一步
  - 删除重复描述和低价值日志式过程记录
- 目标是让新接手者在 2-5 分钟内读完并进入执行状态。

## 4. 多 service 改动规则

如果一次任务改动了多个 service：

- 分别更新各自的 `CONTEXT.md`
- 在主要 service 的 `CONTEXT.md` 里补充跨 service 依赖关系

## 5. 提交建议

- 提交前确认 `CONTEXT.md` 已同步
- commit message 建议包含作用域，如：
  - `docs(agent): update CONTEXT after pdf artifacts migration`
  - `feat(backend): ...`

## 6. 约束优先级

当本文件与子目录内更具体的协作文档冲突时：

1. 以更深层目录文档为准（就近原则）
2. 但“先读 CONTEXT、后更新 CONTEXT”这条原则始终保留
