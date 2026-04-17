# AGENT Operating Guide

本文件定义在本仓库中工作的统一协作约定（面向人和 LLM）。

## 0. 适用范围

- 作用域：仓库根目录下所有 service（如 `agent/`、`backend/`、`frontend/`）
- 目标：确保跨会话、跨模型切换时上下文不断裂

## 1. 开始任何任务前（必须）

1. 先定位你要修改的 service。
2. 先阅读该 service 或目标子包下的 `docs/DESIGN.md`，用它理解当前项目结构、模块边界和主链路。
3. 如果会改到更深一层的子目录/子包，继续就近查找并阅读该层的 `docs/DESIGN.md`。

示例：
- 修改 `agent/`：先读 `agent/docs/DESIGN.md`
- 修改 `agent/ocr_processor/`：先读 `agent/ocr_processor/docs/DESIGN.md`
- 修改 `backend/`：先读 `backend/docs/DESIGN.md`（若存在）
- 修改 `frontend/`：先读 `frontend/docs/DESIGN.md`（若存在）

要求：

- `docs/DESIGN.md` 是理解项目结构的第一入口，不要跳过后直接改代码
- 如果目标目录没有 `docs/DESIGN.md`，但其上层有，则先以上层设计文档为准
- 如果本次改动改变了模块边界、处理流程、目录结构或关键设计决策，完成后必须同步更新对应层级的 `docs/DESIGN.md`

## 2. 提交建议

- 提交前确认相关文档已同步
- commit message 建议包含作用域，如：
  - `docs(agent): update design after pdf artifacts migration`
  - `feat(backend): ...`

## 3. TDD 约定（必须）

- 强制使用 TDD：`red -> green -> refactor`
- 除纯文档修改、纯注释修改、纯重命名且无行为变化的改动外，不允许跳过 TDD
- 不允许先把实现写完再补测试；必须先写或先改测试来定义目标行为
- 如果现有代码缺少测试基础，当前任务也必须先补最小可执行测试，再进入实现
- `red` 阶段至少要确认：
  - 新增测试会失败
  - 失败原因直接对应目标行为，而不是环境噪声
- 未经过可验证的 `red`，不得直接进入 `green`
- `green` 阶段至少要确认：
  - 只做让测试通过所需的最小实现
  - 相关测试全部通过
- 未验证测试通过，不得宣布功能完成
- `refactor` 阶段至少要确认：
  - 没有改变已定义行为
  - 测试在重构后仍保持通过
- 如果任务涉及真实文档或真实样本，除了 synthetic 单元测试外，还应补至少一条基于真实样本的验证测试或文档测试

## 4. 约束优先级

当本文件与子目录内更具体的协作文档冲突时：

1. 以更深层目录文档为准（就近原则）
2. 但“先读设计文档、再开始开发”这条原则始终保留
