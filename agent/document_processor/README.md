# Document Processor

`document_processor` 负责把原始文档交给合适的内部处理器，并产出统一的 `ProcessResult`，供后续抽取或展示使用。

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

## 当前实现结构

当前代码已经落地的是三层结构：

```text
file_obj
  -> document_processor.processor.process(...)
  -> 外层入口做输入校验和文件类型推断
  -> impl/interface.py 里的 InternalProcessorInterface
  -> 内部注册表按 FileType 找到具体处理器
  -> 具体处理器继承 impl/base.py 里的 BaseDocumentProcessor
  -> ProcessResult
```

也就是说：

- `processor.py` 是外层编排入口
- `impl/interface.py` 是 `impl/` 内部固定接口类
- `impl/base.py` 是具体处理器的抽象基类
- 具体处理器通过内部注册机制接入，外部不能显式注入处理器实例

返回结果统一为 `ProcessResult`，主要包括：

- `file_type`
- `filename`
- `markdown`
- `md_list`
- `blocks`
- `meta_info`
- `warnings`

## 当前行为说明

- 当前 `pdf` 和 `docx` 已经有内部注册入口
- 当前注册的 `pdf/docx` 处理器还是占位实现，主要用于固定编排结构和扩展方式
- 真实的 PDF / DOCX 解析算法后续应放到 `impl/` 下的具体处理器类里
- `.doc` 当前仍不支持

## 当前阶段说明

这一层现在已经把“外层编排 / 内部固定接口 / 具体处理器基类 / 注册式扩展”这套骨架固定下来了。下一步补真实算法时，应该直接在 `impl/` 下增加具体处理器类，并通过内部注册机制挂到 `InternalProcessorInterface` 上，而不是回到手写分支分发。
