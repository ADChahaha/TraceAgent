# `test_docx_processor.py`

## 基本实现思路

`impl/docx/processor.py` 是当前 `DOCX` 真实处理器的直接实现文件。它不再停留在“注册到哪一个处理器”这种入口层问题，而是直接负责一条具体 pipeline：

```text
file_obj
  -> `DocxProcessor.process(...)`
  -> 基类校验 read()
  -> 读取 docx 二进制内容
  -> 解析 filename/name，没有就回退成 `document.docx`
  -> 用 `python-docx` 的 `Document(BytesIO(...))` 打开文档
  -> 按 body 顺序遍历 heading / paragraph / table
  -> 转成 markdown
  -> 同时归一化成 `ContentBlock`
  -> 返回 `ProcessResult`
```

这一层最关键的约束有两个：

1. `DOCX` 直接走 `python-docx`，不依赖本机 LibreOffice 一类外部程序。
2. 标题、正文和表格都要能稳定转换成统一的 markdown 与 block 结果。

## 测什么

- `DocxProcessor` 能把真实 `.docx` 样本转成 markdown 和 blocks
- `DocxProcessor` 已经不再暴露 `DocumentConverter`，说明实现不再依赖 `docling`
- 当输入对象没有 `filename/name` 时，`DocxProcessor` 会补默认文件名 `document.docx`

## 每个函数在干什么

`test_docx_processor_uses_python_docx_to_generate_markdown_and_blocks`

- 构造一个包含标题和正文段落的真实 `.docx` 内存文件。
- 直接调用 `DocxProcessor().process(...)`。
- 检查产出的 `markdown`、`md_list` 和 `blocks` 都是实际解析结果，而不是占位 warning。

`test_docx_processor_uses_python_docx_instead_of_docling`

- 直接读取 `impl/docx/processor.py` 模块对象。
- 直接调用 `DocxProcessor().process(...)`。
- 检查模块里已经没有 `DocumentConverter`，并确认正文仍能被正常解析。

`test_docx_processor_uses_default_filename_when_input_has_no_name`

- 构造一个没有 `filename/name` 属性的 docx 内存文件对象。
- 直接调用 `DocxProcessor().process(...)`。
- 检查处理器会把输出文件名补成 `document.docx`。

## 为什么有它

这个测试文件专门对应 `document_processor/impl/docx/processor.py`，把 `DOCX` 真实实现文件自己的职责固定住。这样后面就算入口层、注册表或 route 层继续调整，也不会把 `DocxProcessor` 这条基于 `python-docx` 的处理链路改坏。

## 怎么跑

```bash
conda activate agent-gate
python -m pytest tests/document_processor/test_docx_processor.py -q
```
