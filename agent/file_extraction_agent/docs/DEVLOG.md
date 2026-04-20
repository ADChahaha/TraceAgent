last updated: 2026-04-20 16:15:33 CST

## 2026-04-20 16:15:33

### 已完成工作

- 新增了 `file_extraction_agent/schemas.py` 第一版数据契约，实现了 `TaskSpec`、`GraphInput`、`BroadExtractionOutput`、`ResolvedFieldOutput`、`ExtractionResult` 等基础结构。
- 明确 `GraphInput` 接受的是 backend 聚合后的 session 级输入，顶层必须带 `session_id`，文档级输入必须带 `document_id`。
- 把 `NormalizedDocument.blocks` 从裸 `dict` 列表收紧成结构化的 `NormalizedBlock` / `NormalizedBoundingBox`，明确块级文本、页码、bbox、类型和块级元信息字段。
- 补齐了 `tests/file_extraction_agent/test_schemas.py` 与对应的 `tests/file_extraction_agent/docs/test_schemas.md`，并完成通过验证。

### 当前进展

- `file_extraction_agent` 这一层已经有了可执行的第一版 schema 契约，后续可以直接围绕这些对象继续实现 `processor.py`、`normalization.py` 和 `graph.py`。
- 入口输入的层级已经收敛清楚：这一层不再按“直接吃 document_processor 原始返回值”建模，而是按“backend 补齐业务标识后的 session 级输入”建模。
- 文档块输入也已经从宽松字典收敛成明确对象，后续不需要在实现里长期依赖裸字典字段访问。

### 遇到的问题

- 一开始把 schema 顶部说明写成了流程描述，和这个文件“只定义接受什么、产出什么”的职责不完全匹配，后续已经改成契约导向表述。
- `blocks` 最初用 `list[dict[str, Any]]` 占位虽然快，但会让块结构含义不清楚，也不利于后续 normalization 和 validation 层复用。

### 下一步

- 继续按 TDD 补 `processor.py`，把 session 级输入校验和 task spec 加载落到真正入口。
- 再补 `impl/normalization.py`，把外部 session 输入整理成稳定的 `GraphInput`。
- 然后继续落地 `impl/graph.py` 和后续 broad extraction / resolution 骨架。

## 2026-04-20 13:28:33

### 已完成工作

- 更新了 `file_extraction_agent/docs/DESIGN.md` 中关于 `GraphInput`、`normalization.py` 和 `graph.py` 的职责划分。
- 明确 `GraphInput` 属于 `schemas.py` 中定义的数据契约，不再把它视为 `graph.py` 的内部模板。
- 明确 `impl/normalization.py` 是 graph 外的预处理步骤，由 `processor.py` 先调用，把外部输入整理成 `GraphInput` 后再交给 `impl/graph.py`。

### 当前进展

- 当前设计已经把“数据契约”和“流程内部状态”拆开：
  - `schemas.py` 负责 `GraphInput` 等静态输入输出结构
  - `impl/state.py` 负责流程运行中的中间状态
- 当前设计已经把“输入整形”和“两阶段处理流程”拆开：
  - `impl/normalization.py` 负责外部输入归一化
  - `impl/graph.py` 从 `GraphInput` 开始执行 broad extraction 和 field resolution

### 遇到的问题

- 之前的设计表述里，`normalization.py` 虽然放在 `impl/`，但它处于 graph 内还是 graph 外不够明确，容易让后续实现时把输入整形逻辑混进 `graph.py`。
- `GraphInput` 如果写进 `graph.py`，会让数据契约和流程实现耦合，不利于 `normalization.py` 和 `graph.py` 分层。

### 下一步

- 在真正开始实现前，先按这版设计补 `schemas.py`，明确 `NormalizedDocument`、`GraphInput`、`ExtractionResult` 等结构。
- 再按 TDD 顺序补 `processor.py`、`impl/normalization.py`、`impl/graph.py` 和对应测试。

## 2026-04-19 23:44:10

### 已完成工作

- 补齐了 `file_extraction_agent` 第一版 `docs/DESIGN.md`。
- 明确了模块职责边界：这一层只负责标准化文档上的字段抽取与字段定案，不负责原始文件解析、写库或外层路由判定。
- 收敛了目录结构和分层方案，确定 `state.py`、`prompts.py` 放在 `impl/` 下，作为内部执行细节管理。
- 对设计文档做了一轮表述收敛，去掉了不必要的 AI 相关措辞，改成偏工程实现的描述方式。

### 当前进展

- 已确定第一版主链路为：输入归一化 -> broad extraction -> broad output 校验与标准化 -> field resolution -> `ExtractionResult`。
- 已确定 `graph.py` 的入口应接收归一化后的 `GraphInput` 和抽取执行客户端，而不是大量松散参数。
- 已明确 `task_specs/*.json`、结构化输出对象以及两阶段处理之间的职责边界。

### 遇到的问题

- `file_extraction_agent` 目录当前只有空白的 `docs/DESIGN.md` 和 `docs/DEVLOG.md`，设计边界、目录职责和执行流程都需要先补文档才能支撑后续实现。
- 文档初稿中带有偏背景化、工具化的表达，需要收敛成更稳定的模块设计语言。

### 下一步

- 按 TDD 顺序补 `schemas.py`、`processor.py`、`extractor_client.py` 和 `impl/` 下的执行骨架。
- 同步建立 `tests/file_extraction_agent/` 及其 `tests/docs/` 一一对应测试文档。
- 在实现过程中继续评估 `docs/DESIGN.md` 是否需要随代码落地补充细节。
