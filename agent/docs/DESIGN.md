# Agent Service Design

这份文档面向开发者，记录 `agent service` 的模块边界、主链路和实现约束。服务启动与日常使用请看 [README.md](./agent/README.md)。

## 目标

`agent/` 负责文档处理链路中的三个阶段：

- `document_processor`
- `file_extraction_agent`
- `route_policy_agent`

这一层的目标是把“原始文件处理”“字段抽取”和“LLM route 判断”明确分开，避免一个模块同时承担文件解析、标准化、模型抽取、写库前治理判断和 HTTP 适配。

## 与 Backend 的关系

`agent service` 不直接访问 `backend` 的数据库或底层 storage。

它和 `backend` 的交互方式应当是：

- `backend` 通过 HTTP 把上传 PDF bytes 传给 `document_processor`
- `agent service` 返回 PDF 文件名和抽取友好的语义 HTML fragment
- 如果后续要走字段抽取，`backend` 需要聚合 `document_processor` 返回的 HTML；blocks 留在 backend 侧用于证据回填和 trace 展示
- `backend` 通过 HTTP 把已聚合的 HTML 和外部 `task_spec` 传给 `file_extraction_agent`
- `agent service` 返回字段级 `ExtractionResult(result + trace)`
- `backend` 从字段结果、trace refs 和 trace actions 组装 `field_outputs + refs_with_text + field_processes`，再通过 HTTP 调用 `route_policy_agent`
- `route_policy_agent` 返回字段级 `accept / review / reject`，后续 review、final result 和 audit 都由 `backend` 保存和驱动

也就是说，`agent service` 只负责文档标准化、字段抽取和 route 判断，不负责任务状态、人工审核、字段提交或数据存储管理。

## 当前结构

```text
agent/
├── main.py
├── routes/
│   ├── document_processor.py
│   ├── file_extraction_agent.py
│   └── route_policy_agent.py
├── docs/
│   ├── API.md
│   ├── DESIGN.md
│   └── DEVLOG.md
└── service/
    ├── __init__.py
    ├── document_processor/
    │   ├── processor.py
    │   ├── schemas.py
    │   └── docs/
    │       ├── API.md
    │       └── DESIGN.md
    ├── file_extraction_agent/
    │   ├── processor.py
    │   ├── schemas.py
    │   ├── input_adapter.py
    │   ├── impl/
    │   │   ├── graph.py
    │   │   ├── html_index.py
    │   │   ├── html_state.py
    │   │   ├── html_tools.py
    │   │   ├── model_factory.py
    │   │   └── resolution_new.py
    │   └── docs/
    │       ├── API.md
    │       └── DESIGN.md
    └── route_policy_agent/
        ├── __init__.py
        ├── processor.py
        ├── schemas.py
        ├── input_validator.py
        ├── policy_client.py
        ├── impl/
        │   ├── mapper.py
        │   └── prompts.py
        └── docs/
            ├── DESIGN.md
            └── DEVLOG.md
```

当前 `agent/pyproject.toml` 负责 `agent` 这一层的 FastAPI 入口、`routes/` 和 `service/` 业务包打包。`routes/` 只保留 HTTP 协议适配，真实业务阶段统一放在 `service` 包下，并通过 `service.document_processor`、`service.file_extraction_agent`、`service.route_policy_agent` 这三个导入路径访问。模块内部除 `__init__.py` 外统一使用绝对导入，避免相对导入层级扩散。

当前 `agent` 根层运行时依赖由 [pyproject.toml](./agent/pyproject.toml) 管理，至少包括：

- `fastapi`
- `langgraph`
- `langchain-openai`
- `mineru[core]`
- `onnxruntime`
- `openai`
- `python-multipart`
- `torch`
- `transformers`
- `uvicorn`

## 模块边界

### `document_processor`

- 负责原始 PDF 的读取、MinerU 解析和 HTML/markdown/blocks 导出
- 输出 `ProcessResult(filename + html + display_html + markdown + md_list + blocks + meta_info + warnings)`
- 当前只支持 PDF，固定走 MinerU pipeline，不保留 DOCX、Docling、RapidOCR、Paddle 或 Marker 分支
- 提供两类入口：
  - Python 入口：`service.document_processor.processor.process(...)`
  - HTTP 入口：`routes/document_processor.py`

### `file_extraction_agent`

- 负责消费 `document_processor` 产出的 HTML，完成字段级证据预选与字段定案
- 不负责原始文件解析
- 不负责对外部原始 payload 做第一层必填校验或协议兜底；这一层默认接收外部已经校验好的输入
- 进入这一层前，外部必须先通过独立文件完成 session 输入校验与协议适配，不应把这部分逻辑混进 `processor.py`

当前业务入口包括：

- `service.file_extraction_agent.processor.extract(...)`
- HTTP 入口：`routes/file_extraction_agent.py`

当前 `file_extraction_agent` 使用单 resolution agent：模型根据字段语义和 compact document outline 调用 HTML 工具读取证据并写字段，同时用 Reading Stages 维护右侧可读过程。resolution 必须让每个字段通过 `set_field` 进入 `resolved` 或 `failed`：

```text
backend 聚合后的 html + task_spec
  -> input_adapter.py 校验 html/task_spec/run_options 并组装 HtmlExtractionInput
  -> html_index.py 基于已有 HTML id 构建 document tree、elements、tables 和 row_index；tree 按 DOM/section 容器语义保留 section、heading 和同层 block items 的顺序与预览
  -> resolution_new.py 把 task fields 和 document outline 交给 LangGraph tool-calling loop
  -> resolution model 调用 reading stage 工具维护 append-only 可读阶段和候选证据 notes
  -> resolution model 调用 overview / read_section / read_blocks / read_block_range / read_list / query_table 读取证据
  -> 如果文本块将作为最终证据，先调用 preview_inline_evidence 细化到 inline id
  -> 证据足够或失败明确后调用 set_field 写入字段状态、值、证据 id 和字段级 rationale；resolved 字段强制文本 inline、表格 row、列表 item 粒度
  -> 所有字段 set_field 后调用 finish 做完整性校验
  -> graph 映射成 ExtractionResult(result + trace)
  -> trace 保留 reading_stages、document_tree、field_states 和 actions
```

这个设计不承诺 100% 召回。它的目标是让抽取过程变成可回放的“阶段、读取、查表、记录候选证据、写字段、完成”动作链路；证据不足或工具诊断提示风险时，字段可以先 `failed`，后续由 route policy 和人工 review 接住。所有 reading stage、读取、查表、字段写入和 finish 都必须进入 trace，方便后续审核和调试。

工具边界保持精简：

- `start_stage(title, focus, basis)`：append 新阅读阶段，描述当前要理解什么以及为什么现在看这里；同一时间只允许一个 `in_progress` stage。
- `append_stage_progress(stage_id, type, summary)`：在阶段内追加 `investigate / compare / verify_absence / conclude` 进展；`start_stage` 后必须先追加阅读类 progress 才能读取，`conclude` 不能作为 stage 首个 progress；`compare` 用于多处证据关系决定结论，`verify_absence` 用于缺失类或 `null` 结论前说明已检查范围，但不是每个字段的硬性步骤。
- `record_stage_evidence(stage_id, evidence_ids, observation, supports, limits)`：记录候选证据 note，证据必须是已观察的 inline / table row / list item 粒度。
- `review_stage_evidence(stage_id)`：按记录顺序复看阶段候选证据；不是 `set_field` 前置条件。
- `complete_stage(stage_id, finding)`：写阶段 finding 并标记完成，不额外追加 `conclude` progress。
- `overview()`：返回 section container、heading 和同层 block items 的混排 outline；heading 不会默认拥有后续平级块。
- `read_section(section_id)`：只读取 heading 元素真实后代的章节预览；平级段落、列表和表格由 overview 直接暴露。
- `read_blocks(section_id, indexes)`：按 scope id 和模型选择的 index 列表读取块；section 容器按真实 DOM 后代读，heading 只按真实后代读，叶子块用 `indexes=[0]` 读。
- `read_block_range(section_id, start_index, count)`：按同一 scope 连续读取一段 block，用于顺序补上下文。
- `read_list(section_id, block_offset, item_offset, number)`：对 list block 做分页读取；overview 里的顶层 list id 可以直接配 `block_offset=0` 使用。
- `query_table(section_id, block_offset, sql)`：对 table block 执行安全 SELECT；overview 里的顶层 table id 可以直接配 `block_offset=0` 使用；返回 SQL 行、轻量 `table_audit` 和查询 `summary`。
- `preview_inline_evidence(source_id, start_index, count)`：把已观察到的文本块切成 inline 候选证据，用于写字段前细化文本证据。
- `set_field(name, value, evidence_ids, status, failure_reason, stage_id, rationale)`：写字段值或失败状态，并校验证据 id、证据粒度与字段类型；`rationale` 是字段级理由，`failure_reason` 只在字段失败时使用。字段不再引用单独的 note id，和阶段候选证据 note 通过共享 `evidence_ids` 关联。
- `finish()`：校验所有字段已完成、必填字段和证据一致性。

Reading Stages 不是预生成计划，不约束工具选择，也不替代证据。模型在进入一个大阅读阶段时 append stage，随后先追加 `investigate / compare / verify_absence` 说明为什么开始读或确认什么范围，再调用读取工具；阶段内通过 progress events 和 evidence notes 记录“看了什么、候选依据是什么、得出了什么结论”。一个 stage 只应该覆盖共享同一 section、table、list 或对比链路的一组字段写入；关系不大的下一批字段应先完成当前 stage，再开启新 stage。字段最终仍必须由 `set_field` 和已观察证据决定，`finish` 也不以 stage 完成度作为通过条件。前端可以用 stages 聚合人类可读的阅读过程，同时折叠工具错误、重复 preview 和 finish 校验噪声。

列表和表格都支持 overview 直接入口。模型应先用 document outline 定位目标块；如果 overview 已给出 list id，就直接用 `read_list(list_id, 0, item_offset, number)` 读取列表项，否则先通过 `overview/read_section` 的 block index 选择列表块，再调用 `read_blocks(section_id, [index])` 确认 ref，之后用 `read_list(section_id, block_offset, item_offset, number)` 展开。

表格处理是 `file_extraction_agent` 内部的专用检索能力，而不是业务特例。它只理解通用表格结构和字段提示，不硬编码“学术论文”“文明寝室”等业务词。模型应先用 document outline 定位表格；如果 overview 已给出 table id，就直接用 `query_table(table_id, 0, sql)` 查询，否则再通过 `overview/read_section` 的 block index 选择表格块，必要时调用 `read_blocks(section_id, [index])` 确认 ref，之后用 `query_table(section_id, block_offset, sql)` 查询。`overview` 只给 table id、行数和列名；`query_table` 的 `rows[].values` 直接显示 SQL 选中 cell 是否为空，`table_audit.blank_cells` 给整表每列空 cell 数和前 10 个空值行 id，`summary` 给本次查询返回行数和选中输出列空值数量。字段最终定案通过 `set_field` 引用已观察到的 inline id、list item id 或 table row id；只引用整段文本、list 容器或 table 容器会被拒绝。

当前不把 image 作为抽取对象。文档内容类型先收敛为：

```text
section / heading / text / list / table
```

OCR 或表格结构质量提示不参与 resolution 或 route policy 的自动判断。它只在 backend 组装 review handoff 时作为人工审核辅助信息展示，例如提示某个表格 block 行列错位、空 cell 比例高、文本异常字符多或 block 过长。主抽取链路仍以证据召回、字段定案和 route policy 为准。

抽取阶段使用 LangGraph 工具调用。`impl/graph.py` 负责编排 resolution，模型调用层当前由 `service/file_extraction_agent/impl/model_factory.py` 统一处理：

```text
调用方显式传入 model_config，或部署环境提供 BASE_URL / OPENAI_API_KEY / RESOLUTION_MODEL / MODEL
  -> 如果 resolution 模型名为空，build_chat_model 直接拒绝
  -> 用连接配置创建 langchain_openai.ChatOpenAI(...)
  -> resolution_new 通过 LangGraph tool-calling 执行
  -> 如果构造或 invoke 阶段发生错误，不切换协议重试
```

这样把“连哪个模型服务”和“结构化输出协议怎么选”拆开管理：

- 环境变量负责连接信息、密钥和可选模型名
- HTTP 入参或 `processor.extract(...)` 的 `model_config` 负责显式覆盖模型连接配置
- `model_factory.py` 负责把连接配置合并成 resolution `ChatOpenAI` runnable

resolution 的动作边界由工具 schema 控制：

- `resolution_new.py` 负责执行 Reading Stages、`overview`、`read_section`、`read_blocks`、`read_block_range`、`read_list`、`query_table`、`preview_inline_evidence`、`set_field` 和 `finish`。精确工具参数和读取行为以绑定工具时注入的函数 docstring / schema 为准，resolution system prompt 只保留通用执行策略。

更具体的 schema、校验和任务配置，建议直接查看：

- `service/document_processor/docs/API.md`
- `service/file_extraction_agent/docs/API.md`
- `service/file_extraction_agent/schemas.py`
- `service/file_extraction_agent/impl/resolution_new.py`

### `route_policy_agent`

- 负责消费 `TaskSpec + field_outputs + refs_with_text + field_processes`，用小 LLM 作为第三方评价者判断字段结果应 `accept / review / reject`
- 不负责文档标准化
- 不负责字段抽取或重新定案
- 不直接访问 backend 数据库
- 不写最终结果、不执行人工审核、不生成 audit
- 不读取抽取 agent 的完整 prompt、raw model response 或 chain-of-thought
- 只读取抽取过程摘要，不读取工具返回正文、table row、cell、block_id 列表或 action refs

当前规划入口包括：

- Python 入口：`service.route_policy_agent.processor.evaluate(...)`
- HTTP 入口：`routes/route_policy_agent.py`

这一层只看任务/字段定义、字段输出、refs 中携带的证据文本与来源位置，以及每个字段的抽取过程摘要。过程摘要来自 backend 对 `actions` 的归一化：会保留 reading stage、读取、查表、候选证据记录、字段写入、finish、表格诊断摘要和失败原因等事实，不包含完整原文、表格原始行、cell 列表、action refs 或模型原始推理。更具体的设计见：

对于由其他字段派生的字段，`route_policy_agent` 会按 `validation_rules.source_field/source_fields` 把来源字段的过程摘要作为 `related_field_processes` 注入 prompt。这样数量字段或复制候选字段能看到源字段执行过哪些读取、查表、写字段和定案动作，但仍不会看到工具返回正文或表格行。

route policy 的结构化输出策略也固定为 `tool_call`，显式传入 `json_schema` 或 `auto` 会被拒绝。

- `service/route_policy_agent/docs/DESIGN.md`

## 主链路

```text
raw file
  -> document_processor
  -> html
  -> backend aggregates html when needed
  -> file_extraction_agent
  -> extraction result + trace
  -> route_policy_agent
  -> accept / review / reject
```

整体流程可以展开为：

1. `backend` 创建任务，并在当前请求内读取上传文件 bytes；原始文件不持久化。
2. `backend` 逐个 HTTP 调用 `document_processor`，把 PDF 转成语义 HTML fragment。
3. `backend` 保存或展示 `filename/html`。
4. 如果任务需要字段抽取，`backend` 合并多文档 HTML，文档 blocks 留在 backend 侧用于证据回填和 trace 展示。
5. `backend` 将已校验聚合结果和外部 `task_spec` 交给 `file_extraction_agent`。
6. `file_extraction_agent` 输出字段候选证据、工具留痕和字段最终结果。
7. `backend` 从字段结果、证据 refs 和 trace actions 组装 `field_outputs + refs_with_text + field_processes`，交给 `route_policy_agent`。
8. `route_policy_agent` 先通过 `input_validator` 校验字段名、字段输出、refs 文本和抽取过程摘要完整性，再用小 LLM 输出字段级 `accept / review / reject`。
9. `backend` 保存抽取结果、trace 和 route 决策，并继续驱动 review、field commit 和 audit。

可以理解为：

`raw PDF -> document_processor -> semantic html -> backend prepared blocks -> file_extraction_agent -> extraction result + trace -> route_policy_agent -> route decisions`

## HTTP 出口

`main.py` 只负责创建 FastAPI app 并挂载 router，不直接写业务逻辑。当前 route 层按下面方式工作：

```text
HTTP 请求
  -> main.create_app() 挂载 document_processor / file_extraction_agent / route_policy_agent 三个 router
  -> route 层完成 multipart 或 JSON 协议适配
  -> 调用对应业务入口 process(...) / extract(...) / evaluate(...)
  -> 把业务结果映射成 HTTP 响应
```

当前对外路径是：

- `POST /v1/document-processor/process`
  - 接收上传文件和可选 `file_type`
  - 调用 `service.document_processor.processor.process(...)`
  - 返回 `filename/html`
  - 兼容保留旧路径 `POST /v1/ocr/process`
- `POST /v1/file-extraction-agent/extract`
  - 接收外部已准备好的 `html`、必填 `task_spec`、可选 `run_options` 以及可选模型连接参数
  - 调用 `service.file_extraction_agent.processor.extract(...)`
  - 返回 `ExtractionResult`
- `POST /v1/route-policy-agent/evaluate`
  - 接收 `TaskSpec`、`field_outputs`、`refs_with_text` 和 `field_processes`
  - 调用 `service.route_policy_agent.processor.evaluate(...)`
  - 返回字段级 `accept / review / reject` route 决策

当前暂不引入额外 `src/` 或 `app/` 目录。原因是 `agent/pyproject.toml` 已经按 `main.py`、`routes/` 和 `service/` 业务包打包；`service/` 只承载业务阶段，路由层继续放在 `routes/`，这样可以保持业务代码和 HTTP 适配边界清楚。

## 约束

- route 层只做协议适配，不反向定义业务数据结构
- `document_processor` 只负责文档标准化，不直接做字段抽取
- `file_extraction_agent` 只负责字段抽取和 trace，不内置 route policy
- `route_policy_agent` 只负责字段级 route 判断，不重新抽取字段、不写库
- 任何目录结构或主链路变更，都需要同步更新对应层级的 `docs/DESIGN.md`

## 设计原则

- 预处理和抽取分开
- 抽取和 route 判断分开
- 中间结果明确
- 每个模块只负责单一阶段
- 不直接访问 `backend` 数据库或底层 storage
- 后续可以分别替换或优化各阶段的实现
