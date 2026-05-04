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
    │   │   ├── broad_new.py
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

当前固定采用两阶段流程：broad 负责字段级候选证据召回，resolution 基于候选池做字段最终定案。broad 已经演进为工具化 loop，不再是一次性模型输出：

```text
backend 聚合后的 html + task_spec
  -> input_adapter.py 校验 html/task_spec/run_options 并组装 HtmlExtractionInput
  -> 启动一个共享 broad agent loop，prompt 同时包含所有字段、pending_fields 和全字段候选池
  -> broad agent 只能调用 search_grep / add_broad_candidate / finish_broad
  -> search_grep 同时搜索正文 paragraph 和 table 级索引，query 固定使用 term1 OR term2 OR term3
  -> add_broad_candidate 把命中的 paragraph 或 table refs 写入指定字段候选池
  -> 如果模型把不存在的 ref 传给候选写入工具，runner 记录 tool_error 并把错误作为下一轮工具结果返回给模型修正
  -> 每个字段用 finish_broad 正常退出，记录 enough_evidence / partial_evidence / no_evidence 和结束原因
  -> graph 把 candidate_evidence、broad_search_history 和 finish_broad 结果交给 resolution
  -> 启动一个共享 resolution agent loop，prompt 同时包含所有字段、候选池和已完成定案
  -> resolution agent 可读取候选池；如果候选不足，可以继续调用 search_grep / add_resolution_candidate 补查
  -> 多个字段复用同一来源证据时，broad 必须给每个目标字段显式写入候选
  -> resolution 可调用 add_count_candidate 统计来源字段候选数量，并直接把数字写入目标字段候选池
  -> 每个字段最终返回 final_decision，且必须引用对应字段候选池里的 candidate_id
  -> graph 映射成 ExtractionResult(result + trace)，trace.debug_steps 保留运行级调试步骤
```

这个设计不承诺 100% 召回。它的目标是让系统从“单次 broad 漏了就无法恢复”改成“broad 主动查找候选，resolution 还能二次补查，证据仍不足时交给 route/review”。所有搜索、候选写入、阶段退出和最终定案都必须进入 trace，方便后续审核和调试。

工具边界保持精简：

- `search_grep(field_name, query)`：同时搜索普通文本段落和 table 级索引；paragraph 返回 `ref/text`，table 返回 `ref/section/columns/row_count/hint`，不做最终字段判断。
- `add_broad_candidate(field_name, refs, reason)`：只写 broad 候选证据和写入原因，不改字段值。
- `add_resolution_candidate(field_name, refs | values, reason)`：只写 resolution 二次补证候选；`values` 用于把 count 等工具返回的数字写入候选池。
- `add_count_candidate(field_name, source_field_name, reason)`：只在 resolution 阶段统计来源字段当前候选数量，并把数字作为目标字段候选写入。
- `finish_broad(field_name, status, reason)`：结束指定字段 broad；`status=enough_evidence` 时必须已有候选证据。
- `get_candidate_bundle(field_name)`：供 resolution 读取 broad 已写入的候选证据。
- `final_decision(...)`：只允许 resolution 调用，用候选 `candidate_id` 支撑字段最终值或失败原因。

表格处理是 `file_extraction_agent` 内部的专用检索能力，而不是业务特例。它只理解通用表格结构和字段提示，不硬编码“学术论文”“文明寝室”等业务词。对于列名不固定的表格，模型应通过统一 `search_grep` 做宽召回：根据 `field_name`、`display_name`、`lookup_hints`、`cross_field_hints` 形成查询词，在正文段落、表头、表级摘要和邻近标题中做匹配；命中表格时先把 table 级 ref 写入候选池，字段最终定案仍必须引用候选 `candidate_id`。

当前不把 image 作为抽取对象。文档内容类型先收敛为：

```text
section_header / heading
text / text_line
table
```

OCR 或表格结构质量提示不参与 broad、resolution 或 route policy 的自动判断。它只在 backend 组装 review handoff 时作为人工审核辅助信息展示，例如提示某个表格 block 行列错位、空 cell 比例高、文本异常字符多或 block 过长。主抽取链路仍以证据召回、字段定案和 route policy 为准。

两阶段都使用 LangGraph 工具调用。`impl/graph.py` 负责编排阶段流转，模型调用层当前由 `service/file_extraction_agent/impl/model_factory.py` 统一处理：

```text
调用方显式传入 model_config，或部署环境提供 BASE_URL / OPENAI_API_KEY / BROAD_MODEL / RESOLUTION_MODEL / MODEL
  -> 如果 broad/resolution 模型名为空，build_chat_model 直接拒绝
  -> 用连接配置创建 langchain_openai.ChatOpenAI(...)
  -> broad_new / resolution_new 通过 LangGraph tool-calling 执行
  -> 如果构造或 invoke 阶段发生错误，不切换协议重试
```

这样把“连哪个模型服务”和“结构化输出协议怎么选”拆开管理：

- 环境变量负责连接信息、密钥和可选模型名
- HTTP 入参或 `processor.extract(...)` 的 `model_config` 负责显式覆盖模型连接配置
- `model_factory.py` 负责把连接配置合并成 broad/resolution 两个 `ChatOpenAI` runnable

两阶段的动作边界由工具 schema 控制：

- `broad_new.py` 负责生成 plan 和字段候选读取策略
- `resolution_new.py` 负责执行 `read_element`、`table_extraction`、`paragraph_extraction`、`set_field` 和 `finish`

更具体的 schema、校验和任务配置，建议直接查看：

- `service/document_processor/docs/API.md`
- `service/file_extraction_agent/docs/API.md`
- `service/file_extraction_agent/schemas.py`
- `service/file_extraction_agent/impl/broad_new.py`
- `service/file_extraction_agent/impl/resolution_new.py`

### `route_policy_agent`

- 负责消费 `TaskSpec + field_outputs + refs_with_text + field_processes`，用小 LLM 作为第三方评价者判断字段结果应 `accept / review / reject`
- 不负责文档标准化
- 不负责字段抽取或重新定案
- 不直接访问 backend 数据库
- 不写最终结果、不执行人工审核、不生成 audit
- 不读取抽取 agent 的完整 prompt、raw model response 或 chain-of-thought
- 只读取抽取过程摘要，不读取 search 工具返回的候选正文、table row、cell、block_id 列表或 action refs

当前规划入口包括：

- Python 入口：`service.route_policy_agent.processor.evaluate(...)`
- HTTP 入口：`routes/route_policy_agent.py`

这一层只看任务/字段定义、字段输出、refs 中携带的证据文本与来源位置，以及每个字段 broad / resolution 两阶段的过程摘要。过程摘要只包含统一 `search_grep` 查询词、候选写入数量、broad 结束原因、是否执行 `final_decision` 和失败原因，不包含工具返回结果或完整原文。更具体的设计见：

对于由其他字段派生的字段，`route_policy_agent` 会按 `validation_rules.source_field/source_fields` 把来源字段的过程摘要作为 `related_field_processes` 注入 prompt。这样数量字段或复制候选字段能看到源字段 broad 具体查过哪些关键词，但仍不会看到 search 工具返回正文或表格行。

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
8. `route_policy_agent` 先通过 `input_validator` 校验字段名、字段输出、refs 文本和两阶段过程摘要完整性，再用小 LLM 输出字段级 `accept / review / reject`。
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
  - 接收外部已准备好的 `blocks`、可选 `markdown/md_list`、必填 `task_spec`、可选 `run_options`、`metadata` 以及可选模型连接参数
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
