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
- 如果后续要走字段抽取，`backend` 需要把多个 `filename/html` 组织成 `documents`，并和外部 `task_spec` 一起传给 `file_extraction_agent`
- `file_extraction_agent` 通过 NDJSON stream 返回真实工具事件，`backend` 后续负责消费、入库和转发前端
- `agent service` 不直接写数据库；最终结果也作为 stream 中的 `result_completed` 事件返回
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

- `service.file_extraction_agent.processor.extract_stream(...)`
- HTTP 入口：`routes/file_extraction_agent.py`

当前 `file_extraction_agent` 只有 resolution 阶段。它把多个语义 HTML 文件建模成只读虚拟文件树，让模型通过真实工具事件完成阅读、证据绑定和字段提交：

```text
documents(filename + html) + task_spec
  -> input_adapter.py 校验 documents/task_spec/run_options 并组装 HtmlExtractionInput
  -> html_index.py 解析每个 HTML，生成 /001-filename-title/... 虚拟文件树和 path -> node 索引
  -> section header 变成目录，paragraph/list/table 分别变成 .md/.list/.table 文件
  -> resolution_new.py 把 task fields、schema 说明和虚拟树工具交给 LangGraph tool-calling loop
  -> 模型用 tree/read/anchors/query_table 定位材料，并在每次主动动作里写用户可见 reason
  -> 模型用 bind_evidence(field_id, evidence, reason) 先绑定字段候选证据
  -> 如果字段有候选证据，模型必须先用 review_field(field_id, reason) 复看候选证据
  -> 模型用 write_field(field_id, value, final_evidence, status, reason) 覆盖写入字段值和最终证据
  -> submit_result 内部做 schema、类型和 evidence selector 校验
  -> graph.py 按工具调用顺序输出 NDJSON 事件，最终用 result_completed 返回 fields[] 和 trace
```

这个设计不承诺 100% 召回。它的目标是让抽取过程变成可回放的“展开目录、读取文件、查询表格、写字段、提交结果”动作链路；证据不足时字段可以写成 `missing`，后续由 route policy 和人工 review 接住。所有工具开始、完成、失败、字段写入和最终结果都必须进入 stream 事件，方便后续审核和调试。

工具边界保持精简：

- `tree(path, depth, reason)`：展开虚拟文件树，只返回目录和文件名，不返回正文。
- `read(path, offset, limit, reason)`：读取 `.md/.list/.table` 文件；paragraph 返回纯正文，list/table 返回带 metadata 和编号的 Markdown。
- `anchors(path, reason)`：只用于 `.md` paragraph，返回 `Sxxx` 句子编号和短 preview。
- `query_table(path, sql, offset, limit, reason)`：只用于 `.table` 文件，在内存 SQLite 表 `data` 上执行安全 SELECT，并保留原始 `Rxxx` 行号。
- `bind_evidence(field_id, evidence, reason)`：给一个 schema 字段绑定 selector 候选证据，不提交字段值。
- `review_field(field_id, reason)`：只读复看一个字段的 schema 描述、当前值和已绑定候选证据文本；有候选证据时写字段前必须调用。
- `write_field(field_id, value, final_evidence, status, reason)`：对一个 schema 字段做可覆盖定案；`final_evidence` 必须从该字段候选证据中选择，数组字段也一次写入完整数组。
- `submit_result(reason)`：内部校验当前字段缓冲区，成功返回最终结果，失败返回结构化错误供模型继续修正。

paragraph 的证据 selector 使用 `{path, sentences:["S001"]}`，list 使用 `{path, items:["I001"]}`，table 使用 `{path, rows:["R001"]}`。`reason` 是用户可见动作说明，不是证据；证据文本必须能通过虚拟路径和文件内编号反查回原文。

列表和表格都是文件内阅读对象，不拆成子文件。`read(.list)` 会返回 frontmatter metadata 和 Markdown list，列表项编号为 `I001`、`I001.001`；`read(.table)` 会返回 frontmatter metadata 和 Markdown table，行编号为 `R001`。大表需要按条件定位时，模型改用 `query_table(.table, sql)` 分页查询。

paragraph 文件名使用同级编号加段落前 `n` 个清洗后的可见字符，例如 `001-公司成立于2020年.md`。这个名字只是导航预览；完整正文只能通过 `read(path)` 读取，句子级证据只能通过 `anchors(path)` 获取。

当前不把 image 作为抽取对象。文档内容类型先收敛为：

```text
section / heading / text / list / table
```

OCR 或表格结构质量提示不参与 resolution 或 route policy 的自动判断。它只在 backend 组装 review handoff 时作为人工审核辅助信息展示，例如提示某个表格 block 行列错位、空 cell 比例高、文本异常字符多或 block 过长。主抽取链路仍以证据召回、字段定案和 route policy 为准。

抽取阶段使用 LangGraph 工具调用。`impl/graph.py` 负责编排流式事件，模型调用层当前由 `service/file_extraction_agent/impl/model_factory.py` 统一处理：

```text
调用方显式传入 model_config，或部署环境提供 BASE_URL / OPENAI_API_KEY / RESOLUTION_MODEL / MODEL
  -> 如果 resolution 模型名为空，build_chat_model 直接拒绝
  -> 用连接配置创建 langchain_openai.ChatOpenAI(...)
  -> resolution_new 通过 LangGraph tool-calling 执行
  -> graph.py 将工具事件序列化成 NDJSON
  -> 如果构造或 invoke 阶段发生错误，不切换协议重试
```

这样把“连哪个模型服务”和“结构化输出协议怎么选”拆开管理：

- 环境变量负责连接信息、密钥和可选模型名
- HTTP 入参或 `processor.extract_stream(...)` 的 `model_config` 负责显式覆盖模型连接配置
- `model_factory.py` 负责把连接配置合并成 resolution `ChatOpenAI` runnable

动作边界由工具 schema 控制：

- `resolution_new.py` 负责执行 `tree`、`read`、`anchors`、`query_table`、`write_field` 和 `submit_result`。精确工具参数和读取行为以绑定工具时注入的函数 docstring / schema 为准，resolution system prompt 只保留通用执行策略、schema 抽取要求和 evidence selector 约束。

更具体的 schema、校验和任务配置，建议直接查看：

- `service/document_processor/docs/API.md`
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

这一层只看任务/字段定义、字段输出、refs 中携带的证据文本与来源位置，以及 resolution 过程摘要。过程摘要来自 backend 对 `actions` 或 NDJSON 工具事件的归一化：会保留展开目录、读取、查表、字段写入、提交结果和失败原因等事实，不包含完整原文、表格原始行、cell 列表、action refs 或模型原始推理。更具体的设计见：

对于由其他字段派生的字段，`route_policy_agent` 会按 `validation_rules.source_field/source_fields` 把来源字段的过程摘要作为 `related_field_processes` 注入 prompt。这样数量字段或复制候选字段能看到源字段执行过哪些展开目录、读取、查表、写字段和定案动作，但仍不会看到工具返回正文或表格行。

route policy 的结构化输出策略也固定为 `tool_call`，显式传入 `json_schema` 或 `auto` 会被拒绝。

- `service/route_policy_agent/docs/DESIGN.md`

## 主链路

```text
raw file
  -> document_processor
  -> documents(filename + html)
  -> file_extraction_agent stream
  -> result_completed(fields[] + trace)
  -> route_policy_agent
  -> accept / review / reject
```

整体流程可以展开为：

1. `backend` 创建任务，并在当前请求内读取上传文件 bytes；原始文件不持久化。
2. `backend` 逐个 HTTP 调用 `document_processor`，把 PDF 转成语义 HTML fragment。
3. `backend` 保存或展示 `filename/html`。
4. 如果任务需要字段抽取，`backend` 把多个文件整理为 `documents`；文档 blocks 留在 backend 侧用于证据回填和 trace 展示。
5. `backend` 将已校验 `documents` 和外部 `task_spec` 交给 `file_extraction_agent` 的 stream 入口。
6. `file_extraction_agent` 输出 NDJSON 工具事件、字段写入事件和最终 `result_completed`。
7. `backend` 从字段结果、证据 refs 和工具事件组装 `field_outputs + refs_with_text + field_processes`，交给 `route_policy_agent`。
8. `route_policy_agent` 先通过 `input_validator` 校验字段名、字段输出、refs 文本和两阶段过程摘要完整性，再用小 LLM 输出字段级 `accept / review / reject`。
9. `backend` 保存抽取结果、trace 和 route 决策，并继续驱动 review、field commit 和 audit。

可以理解为：

`raw PDF -> document_processor -> documents(filename + html) -> file_extraction_agent stream -> result_completed -> route_policy_agent -> route decisions`

## HTTP 出口

`main.py` 只负责创建 FastAPI app 并挂载 router，不直接写业务逻辑。当前 route 层按下面方式工作：

```text
HTTP 请求
  -> main.create_app() 挂载 document_processor / file_extraction_agent / route_policy_agent 三个 router
  -> route 层完成 multipart 或 JSON 协议适配
  -> 调用对应业务入口 process(...) / extract_stream(...) / evaluate(...)
  -> 把业务结果映射成 HTTP 响应
```

当前对外路径是：

- `POST /v1/document-processor/process`
  - 接收上传文件和可选 `file_type`
  - 调用 `service.document_processor.processor.process(...)`
  - 返回 `filename/html`
  - 兼容保留旧路径 `POST /v1/ocr/process`
- `POST /v1/file-extraction-agent/extract/stream`
  - 接收外部已准备好的 `documents`、必填 `task_spec`、可选 `run_options` 以及可选模型连接参数
  - 调用 `service.file_extraction_agent.processor.extract_stream(...)`
  - 返回 `application/x-ndjson`，每行是一个工具事件或最终 `result_completed`
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
