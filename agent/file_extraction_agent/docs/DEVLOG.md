last updated: 2026-04-20 16:45:20 CST

## 2026-04-20 16:45:20

### 已完成工作

- 更新了 `file_extraction_agent/docs/DESIGN.md`，把 `input_adapter.py` 的职责从“校验 + task spec 加载 + GraphInput 组装”收紧成“只负责输入校验和协议适配”。
- 明确 `processor.py` 继续负责 `task spec` 加载和流程编排，不把这部分职责前移到独立输入适配文件。
- 明确 `impl/normalization.py` 的输入改成“已校验输入 + task spec”，它负责内部归一化并组装 `GraphInput`，而不是承担第一层外部输入适配。

### 当前进展

- `file_extraction_agent` 入口前的职责现在拆成了三段：
  - `input_adapter.py` 负责外部 payload 校验和协议适配
  - `processor.py` 负责 `task spec` 加载和流程编排
  - `impl/normalization.py` 负责把已收敛输入组装成 `GraphInput`
- 这样后续实现时，外部边界问题和模块内部编排问题不会继续混在同一个文件里。

### 遇到的问题

- 之前把 `input_adapter.py` 写得过宽，连 `task spec` 加载都放了进去，会让“外部输入适配”和“业务流程编排”再次耦合。
- 如果不把这层职责及时收紧，后续实现 `processor.py` 时容易出现入口文件和编排入口之间的职责争抢。

### 下一步

- 后续写 `input_adapter.py` 时，只围绕输入校验、协议适配和类型收敛建模，不再把 `task spec` 加载塞进去。
- 再按这条边界继续落地 `processor.py` 与 `impl/normalization.py` 的实现和测试。

## 2026-04-20 16:35:46

### 已完成工作

- 更新了 `agent/docs/DESIGN.md` 和 `file_extraction_agent/docs/DESIGN.md`，把 `processor.py` 的职责从“负责输入校验”收口成“只接收外部已校验输入并做流程编排”。
- 明确 `file_extraction_agent` 不负责对外部原始 payload 做第一层必填校验或协议兜底，这一步应由外部层先完成。
- 同步把 `impl/normalization.py` 的职责改写成“处理已校验输入的内部归一化”，避免后续实现时把坏输入兜底逻辑重新塞回模块内部。

### 当前进展

- `file_extraction_agent` 的边界现在更清楚了：
  - 外部层负责 session 输入校验和协议适配
  - `processor.py` 负责 task spec 加载、`GraphInput` 组装和 graph 编排
  - `normalization.py` 负责已校验输入到内部契约的转换
- 这样后续真正写 `processor.py` 时，可以直接围绕“已校验 typed input”建模，而不是一边编排一边做原始 payload 防御式校验。

### 遇到的问题

- 之前文档把 `processor.py` 写成“对外统一入口并负责输入校验”，容易把外部协议校验职责和模块内部编排职责混在一起。
- 如果不先把这个边界写死，后续实现时很容易出现 route、backend 聚合层、`processor.py` 三处重复校验同一份输入的问题。

### 下一步

- 后续实现 `processor.py` 时，直接按“输入已经在外部校验完成”的前提设计入口签名和内部流程。
- 再根据这条边界继续收敛 `normalization.py`、`graph.py` 和对应测试的输入模型。

## 2026-04-20 16:25:47

### 已完成工作

- 补齐了 `file_extraction_agent/extractor_client.py`，现在会从环境变量读取 `BASE_URL`、`OPENAI_API_KEY`、`MODEL`，并构造真正可调用的结构化抽取客户端。
- 新增了 `file_extraction_agent/model_client_config.json`，把结构化输出策略从连接配置中拆开，单独管理 `json_schema`、`tool_call`、`auto` 和 fallback 顺序。
- 在 `extractor_client.py` 中加入结构化输出协议回退逻辑：优先尝试 `json_schema`，兼容接口不支持时再退到 `tool_call`；内部把 `tool_call` 映射到 LangChain 的 `function_calling`。
- 补齐了 `tests/file_extraction_agent/test_extractor_client.py` 和对应的 `tests/file_extraction_agent/docs/test_extractor_client.md`。
- 同步更新了 `agent/docs/DESIGN.md` 和 `file_extraction_agent/docs/DESIGN.md`，把连接配置与策略配置的分工、以及结构化输出 fallback pipeline 写清楚。

### 当前进展

- `file_extraction_agent` 这一层现在已经有了可直接复用的模型客户端入口，后续 `processor.py`、`broad_extraction.py` 和 `resolution.py` 可以直接依赖这个 client，而不用各自关心 OpenAI 兼容接口的差异。
- 模型配置职责已经拆开：
  - 环境变量负责服务地址、密钥和模型名
  - `model_client_config.json` 负责结构化输出协议和请求参数
- 新增的客户端测试已经覆盖固定 `json_schema`、固定 `tool_call`、以及 `auto` 回退三种主要路径。

### 遇到的问题

- 一开始把结构化输出固定写死成 `json_schema`，但 OpenAI 兼容接口对这一协议的支持并不稳定，容易在切换供应商或代理层时直接失败。
- LangChain 真实接口里对应的方法名不是仓库内部更直观的 `tool_call`，而是 `function_calling`，因此需要在 `extractor_client.py` 里做一层映射，避免配置语义和底层 SDK 术语耦合。
- 顺手回归时发现 `tests/file_extraction_agent/test_schemas.py` 当前依赖一个现存不一致：它导入了 `NormalizedBlock`，但当前 `schemas.py` 里没有这个符号；这不是这次 client 改动引入的问题。

### 下一步

- 在 `processor.py` 或后续 graph 节点实现中接入 `build_extractor_client_from_env(...)`，把这层客户端真正串进 broad extraction 和 field resolution 流程。
- 等 `schemas.py` 与 `test_schemas.py` 的现存不一致单独收敛后，再做更完整的 file extraction agent 回归验证。

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
