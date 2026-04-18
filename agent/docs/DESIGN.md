# Agent Service Design

这份文档面向开发者，记录 `agent service` 的模块边界、主链路和实现约束。服务启动与日常使用请看 [README.md](./agent/README.md)。

## 目标

`agent/` 负责文档处理链路中的两个阶段：

- `document_processor`
- `file_extraction_agent`

这一层的目标是把“原始文件处理”和“字段抽取”明确分开，避免一个模块同时承担文件解析、标准化、模型抽取和 HTTP 适配。

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
│   └── document_processor.py
├── docs/
│   └── DESIGN.md
├── document_processor/
│   ├── processor.py
│   ├── schemas.py
│   ├── types.py
│   ├── impl/
│   └── docs/DESIGN.md
└── file_extraction_agent/
```

当前 `agent/pyproject.toml` 负责 `agent` 这一层的 FastAPI 入口和 `routes/`，并且为了让 `agent-service` 单独安装后也能启动，当前会一并打包 `document_processor`。`document_processor` 仍保留自己的 `document_processor/pyproject.toml`，便于独立开发与测试。模块内部除 `__init__.py` 外统一使用绝对导入，避免相对导入层级扩散。

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
  - Python 入口：`document_processor.process(...)`
  - HTTP 入口：`routes/document_processor.py`

### `file_extraction_agent`

- 负责消费多文档 block/markdown 输入，完成字段候选生成与字段定案
- 不负责原始文件解析

当前业务入口包括：

- `file_extraction_agent.processor.extract(...)`
- `file_extraction_agent.model_client.build_model_client_from_env(...)`

当前固定采用两阶段流程：

1. broad extraction：一次读取全部 block，为每个 schema 字段生成候选列表
2. field resolution：读取所有字段候选，再按字段逐个定案

两阶段都使用严格结构化输出。LangGraph 负责编排阶段流转，模型调用层当前使用 `langchain_openai.ChatOpenAI(...).with_structured_output(..., method="json_schema", strict=True)` 返回 Pydantic 结果。

两层结构化输出当前分别由不同的 Pydantic schema 控制：

- 第一层 `broad extraction` 绑定 `BroadExtractionOutput`
- 第二层 `field resolution` 绑定 `ResolvedFieldOutput`

更具体的 schema、校验和任务配置，建议直接查看：

- `file_extraction_agent/task_specs/*.json`
- `file_extraction_agent/schemas.py`
- `file_extraction_agent/impl/validation.py`

## 主链路

```text
raw file
  -> document_processor
  -> normalized markdown + blocks
  -> backend session aggregation
  -> file_extraction_agent
  -> extraction result
```

整体流程可以展开为：

1. `backend` 创建任务并保存原始文件。
2. `agent service` 通过 `backend` 内部 API 获取任务输入和文件。
3. 交给 `document_processor` 做文档标准化。
4. 得到 Markdown 优先的标准化结果。
5. `backend` 按 session 聚合多个文档的 block list。
6. 将聚合结果交给 `file_extraction_agent`。
7. 输出字段候选和字段最终结果。
8. 将结果回传给 `backend`。

可以理解为：

`raw file -> document_processor -> normalized markdown + blocks -> backend session aggregation -> file_extraction_agent -> extraction result`

## 约束

- route 层只做协议适配，不反向定义业务数据结构
- `document_processor` 只负责文档标准化，不直接做字段抽取
- 任何目录结构或主链路变更，都需要同步更新对应层级的 `docs/DESIGN.md`

## 设计原则

- 预处理和抽取分开
- 中间结果明确
- 每个模块只负责单一阶段
- 不直接访问 `backend` 数据库或底层 storage
- 后续可以分别替换或优化两个阶段的实现
