# Agent Service

## 说明

`agent` 目录负责文档处理链路中的处理与抽取部分。

当前内部拆分为两个阶段：

- `ocr_processor`
- `file_extraction_agent`

这两个模块职责不同，因此保持分开。

## 与 Backend 的关系

`agent service` 不直接访问 `backend` 的数据库或底层 storage。

它和 `backend` 的交互方式应当是：

- 从 `backend` 的内部 API 获取任务输入
- 从 `backend` 的内部 API 获取原始文件
- 处理完成后再把结果回传给 `backend`

也就是说，`agent service` 只负责处理，不负责数据存储管理。

## 目录结构

```text
agent/
├── README.md
├── main.py
├── pyproject.toml
├── ocr_processor/
│   └── pyproject.toml
├── routes/
│   ├── __init__.py
│   └── ocr_processor.py
└── file_extraction_agent/
```

当前 `agent/pyproject.toml` 只服务 `file_extraction_agent`；`ocr_processor` 作为独立包使用自己的 `ocr_processor/pyproject.toml`。模块内部除 `__init__.py` 外统一使用绝对导入，避免相对导入层级扩散。

其中：

- `ocr_processor.processor.process(...)` 是业务接口
- `routes/ocr_processor.py` 是 HTTP 适配层
- `agent/main.py` 只负责创建 FastAPI app 并挂载 router

## 模块职责

### `ocr_processor`

负责 OCR、文档预处理和中间表示构建。

输入：

- 由 `backend` 内部 API 提供的原始文件，例如 `pdf`、`docx`

输出：

- 处理后的 Markdown
- 对应的内容块列表

它的目标不是直接做信息抽取，而是把原始文件转换成后续抽取阶段更容易使用的标准化输入。

当前链路明确保留两套并行接口：

- Python 业务调用使用 `process(...)`
- HTTP 调用使用 `routes/ocr_processor.py`

两者并行存在，但不要互相耦合：route 层只做协议转换，不反向定义业务层对象。

### `file_extraction_agent`

负责真正的文档抽取。

输入：

- `ocr_processor` 输出的 Markdown 和内容块

输出：

- 抽取结果

它的目标是在已经完成预处理的文本基础上执行实际的信息提取。

## 当前处理流程

整体流程如下：

1. `backend` 创建任务并保存原始文件。
2. `agent service` 通过 `backend` 内部 API 获取任务输入和文件。
3. 交给 `ocr_processor` 做 OCR 和预处理。
4. 得到 Markdown 优先的标准化结果。
5. 将该结果交给 `file_extraction_agent`。
6. 输出最终抽取结果。
7. 将结果回传给 `backend`。

可以理解为：

`raw file -> ocr_processor -> normalized markdown + blocks -> file_extraction_agent -> extraction result`

## 设计原则

- 预处理和抽取分开
- 中间结果明确
- 每个模块只负责单一阶段
- 不直接访问 `backend` 数据库或底层 storage
- 后续可以分别替换或优化两个阶段的实现
