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
└── file_extraction_agent/
```

## 模块职责

### `ocr_processor`

负责 OCR、文档预处理和中间表示构建。

输入：

- 由 `backend` 内部 API 提供的原始文件，例如 `pdf`、`docx`

输出：

- 处理后的文本
- 文本对应的 meta info

它的目标不是直接做信息抽取，而是把原始文件转换成后续抽取阶段更容易使用的标准化输入。

### `file_extraction_agent`

负责真正的文档抽取。

输入：

- `ocr_processor` 输出的带 meta info 的文本

输出：

- 抽取结果

它的目标是在已经完成预处理的文本基础上执行实际的信息提取。

## 当前处理流程

整体流程如下：

1. `backend` 创建任务并保存原始文件。
2. `agent service` 通过 `backend` 内部 API 获取任务输入和文件。
3. 交给 `ocr_processor` 做 OCR 和预处理。
4. 得到带 meta info 的文本结果。
5. 将该结果交给 `file_extraction_agent`。
6. 输出最终抽取结果。
7. 将结果回传给 `backend`。

可以理解为：

`raw file -> ocr_processor -> normalized text with meta info -> file_extraction_agent -> extraction result`

## 设计原则

- 预处理和抽取分开
- 中间结果明确
- 每个模块只负责单一阶段
- 不直接访问 `backend` 数据库或底层 storage
- 后续可以分别替换或优化两个阶段的实现
