# `test_schemas.py`

## 基本实现思路

`service.document_processor.schemas` 只定义 PDF 转 HTML 的返回结构，不参与文件读取、类型判断或 docling 调用。

```text
filename + html
  -> ProcessResult(filename, html)
```

## 测什么

- `ProcessResult` 只暴露 `filename` 和 `html` 两个字段。
- `ProcessResult` 可以被 `asdict()` 展开成普通字典。

## 每个函数在干什么

`test_process_result_exposes_only_filename_and_html`

- 构造最小 `ProcessResult`。
- 检查它是 dataclass。
- 检查字段顺序固定为 `filename/html`。

`test_process_result_serializes_as_plain_dataclass_data`

- 构造一个带 HTML 的 `ProcessResult`。
- 用 `asdict()` 展开。
- 检查展开结果只包含 `filename` 和 `html`。

## 怎么跑

```bash
conda activate agent-gate
python -m pytest tests/document_processor/test_schemas.py -q
```
