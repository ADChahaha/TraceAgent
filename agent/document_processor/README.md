# Document Processor

`document_processor` 负责把原始文档处理成统一的 Markdown 和 block 结果，供后续抽取或展示使用。

## 支持的文件类型

- `pdf`
- `docx`

当前不支持：

- `doc`

## Usage

```python
from document_processor.processor import process

result = process(file_obj, file_type=None)
```

其中：

- `file_obj` 建议传文件对象，而不是文件路径
- `file_type` 可省略；如果文件名可识别，会自动推断

返回结果统一为 `ProcessResult`，主要包括：

- `markdown`
- `md_list`
- `blocks`
- `meta_info`
- `warnings`

`pdf` 首次运行时，如果本地还没有 Docling 所需模型，处理器会自动下载对应 artifacts，首次耗时会明显更长。

## 当前行为说明

- `pdf` 使用 Docling 处理
- `docx` 使用 Docling 处理
- `pdf` 默认优先复用本地 Docling artifacts；如果缺失，会自动下载后再继续处理
- 如果 Docling 失败，处理会直接报错
- `.doc` 当前返回未实现结果
