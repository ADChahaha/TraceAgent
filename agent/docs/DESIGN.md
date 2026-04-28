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

- 从 `backend` 的内部 API 获取任务输入
- 从 `backend` 的内部 API 获取原始文件
- 处理完成后再把结果回传给 `backend`

也就是说，`agent service` 只负责处理，不负责数据存储管理。

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
    │   ├── types.py
    │   ├── impl/
    │   └── docs/
    │       ├── API.md
    │       └── DESIGN.md
    ├── file_extraction_agent/
    │   ├── processor.py
    │   ├── schemas.py
    │   ├── extractor_client.py
    │   ├── input_adapter.py
    │   ├── impl/
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

- `docling`
- `fastapi`
- `langgraph`
- `langchain-openai`
- `openai`
- `python-docx`
- `python-multipart`
- `uvicorn`

## 模块边界

### `document_processor`

- 负责原始 `pdf/docx` 的读取、OCR、结构化块提取和 Markdown 标准化
- 输出统一 `ProcessResult(blocks + md_list + markdown + meta_info + warnings)`
- 提供两类入口：
  - Python 入口：`service.document_processor.processor.process(...)`
  - HTTP 入口：`routes/document_processor.py`

### `file_extraction_agent`

- 负责消费多文档 block/markdown 输入，完成字段级证据预选与字段定案
- 不负责原始文件解析
- 不负责对外部原始 payload 做第一层必填校验或协议兜底；这一层默认接收外部已经校验好的输入
- 进入这一层前，外部必须先通过独立文件完成 session 输入校验与协议适配，不应把这部分逻辑混进 `processor.py`

当前业务入口包括：

- `service.file_extraction_agent.processor.extract(...)`
- `service.file_extraction_agent.extractor_client.build_extractor_client(...)`
- HTTP 入口：`routes/file_extraction_agent.py`

当前固定采用两阶段流程：

1. broad extraction：一次读取全部 block，为每个 schema 字段生成证据 bundle
2. field resolution：逐字段读取 broad evidence，必要时请求工具补查，再输出字段最终结果

两阶段都使用结构化输出，但不再假设所有 OpenAI 兼容接口都支持同一种结构化协议。`impl/graph.py` 负责编排阶段流转，模型调用层当前由 `service/file_extraction_agent/extractor_client.py` 统一处理：

```text
调用方显式传入 base_url / openai_api_key / model，或部署环境提供 BASE_URL / OPENAI_API_KEY / MODEL
  -> 如果 MODEL 仍为空，extractor_client 使用代码内默认模型
  -> structured_output_strategy 由 processor.extract(...) 显式参数传入，默认 auto
  -> 用连接配置创建 langchain_openai.ChatOpenAI(...)
  -> 如果 strategy=json_schema，就用 with_structured_output(..., method="json_schema", strict=True)
  -> 如果 strategy=tool_call，就改用 with_structured_output(..., method="function_calling", strict=True)
  -> 如果 strategy=auto，就先试 json_schema，再在不支持时回退到 tool_call
  -> broad extraction / field resolution 继续收到同样的 Pydantic 结构化结果
```

这样把“连哪个模型服务”和“结构化输出协议怎么选”拆开管理：

- 环境变量负责连接信息、密钥和可选模型名；如果没有 MODEL，`extractor_client.py` 使用代码内默认模型
- `processor.extract(...)` 的显式参数负责结构化输出策略
- `extractor_client.py` 负责把连接配置和策略合并成统一可调用 agent

两层结构化输出当前分别由不同的 Pydantic schema 控制：

- 第一层 `broad extraction` 绑定内部 `EvidenceCollection`
- 第二层 `field resolution` 按字段绑定内部 `FieldResolutionAction`

更具体的 schema、校验和任务配置，建议直接查看：

- `service/document_processor/docs/API.md`
- `service/file_extraction_agent/docs/API.md`
- `service/file_extraction_agent/schemas.py`
- `service/file_extraction_agent/impl/resolution.py` 中的 `validation_rules` 后处理逻辑

### `route_policy_agent`

- 负责消费 `TaskSpec + field_outputs + refs_with_text`，用小 LLM 作为第三方评价者判断字段结果应 `accept / review / reject`
- 不负责文档标准化
- 不负责字段抽取或重新定案
- 不直接访问 backend 数据库
- 不写最终结果、不执行人工审核、不生成 audit
- 不读取抽取 agent 的完整 prompt、raw model response、chain-of-thought、trace actions 或额外风险标记

当前规划入口包括：

- Python 入口：`service.route_policy_agent.processor.evaluate(...)`
- HTTP 入口：`routes/route_policy_agent.py`

这一层只看任务/字段定义、字段输出和 refs 中携带的证据文本与来源位置，不读取完整原文。更具体的设计见：

- `service/route_policy_agent/docs/DESIGN.md`

## 主链路

```text
raw file
  -> document_processor
  -> normalized markdown + blocks
  -> backend session aggregation
  -> file_extraction_agent
  -> extraction result + trace
  -> route_policy_agent
  -> accept / review / reject
```

整体流程可以展开为：

1. `backend` 创建任务并保存原始文件。
2. `agent service` 通过 `backend` 内部 API 获取任务输入和文件。
3. 交给 `document_processor` 做文档标准化。
4. 得到 Markdown 优先的标准化结果。
5. `backend` 按 session 聚合多个文档的 block list。
6. 先由外部独立输入适配文件完成 session 输入校验和协议适配，再将已校验聚合结果交给 `file_extraction_agent`。
7. 输出字段 evidence、工具/规则留痕和字段最终结果。
8. backend 从字段结果和证据 refs 组装 `field_outputs + refs_with_text`，交给 `route_policy_agent`。
9. `route_policy_agent` 先通过 `input_validator` 校验字段名、字段输出和 refs 文本完整性，再用小 LLM 输出字段级 `accept / review / reject`。
10. 将抽取结果、trace 和 route 决策回传给 `backend`，由 backend 保存状态、review 和 audit。

可以理解为：

`raw file -> document_processor -> normalized markdown + blocks -> backend session aggregation -> file_extraction_agent -> extraction result + trace -> route_policy_agent -> route decisions`

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
  - 返回 `ProcessResult` 对应的 JSON 形状
  - 兼容保留旧路径 `POST /v1/ocr/process`
- `POST /v1/file-extraction-agent/extract`
  - 接收标准化后的 `blocks`、可选 `markdown/md_list`、必填 `task_spec`、可选 `run_options`、`metadata` 以及可选模型连接参数
  - 调用 `service.file_extraction_agent.processor.extract(...)`
  - 返回 `ExtractionResult`
- `POST /v1/route-policy-agent/evaluate`
  - 接收 `TaskSpec`、`field_outputs` 和 `refs_with_text`
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
