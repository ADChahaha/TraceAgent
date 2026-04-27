# `test_types.py`

## 基本实现思路

`document_processor.types` 这一层负责把外部输入里比较松散的文件类型信息，归一化成内部统一使用的 `FileType`。它的工作顺序很简单：

1. 如果调用方显式传了 `file_type`，就先解析这个值。
2. 如果没传，就从文件对象上的 `filename` 或 `name` 提取后缀。
3. 再把这些字符串统一规范化成内部的 `FileType.PDF` 或 `FileType.DOCX`。
4. 如果两条路都无法得到支持的类型，就抛出 `UnsupportedFileTypeError`。

也就是说，这一层的核心职责不是“处理文档内容”，而是“把入口处的类型信息变成可靠的内部枚举”。下面这些测试就是围绕这件事展开的。

一句话：这个文件用来固定 `document_processor.types` 的文件类型推断规则，避免后面改动时把显式类型、后缀推断和报错行为改乱。

## 测什么

- 显式传入支持的 `file_type` 时会直接规范化
- 显式传入已经归一化好的 `FileType` 枚举时会原样接受
- 显式类型支持带点前缀的写法
- 省略 `file_type` 时会按文件名后缀推断
- 不支持的显式类型会报错
- 未知文件后缀会报错
- 既没有显式类型也没有可识别文件名时会报错

## 每个函数在干什么

`test_infer_file_type_returns_explicit_supported_type_without_filename_lookup`

- 构造一个文件名不可用的场景。
- 显式传入 `"PDF"`。
- 检查返回值会被规范化成 `FileType.PDF`，说明显式类型优先。

`test_infer_file_type_accepts_file_type_enum_without_stringifying_name`

- 构造一个文件名不可用的场景。
- 显式传入 `FileType.PDF`。
- 确认入口不会把枚举错误转成 `"FileType.PDF"`，而是直接返回内部枚举。

`test_infer_file_type_accepts_dot_prefixed_supported_type`

- 不依赖文件名。
- 显式传入 `".docx"`。
- 检查带点前缀的输入也能被识别成 `FileType.DOCX`。

`test_infer_file_type_uses_filename_extension_when_type_is_omitted`

- 不传 `file_type`。
- 给文件对象一个大小写混合的 `.PdF` 文件名。
- 检查函数会按后缀推断出 `FileType.PDF`。

`test_infer_file_type_rejects_unsupported_explicit_type`

- 显式传入当前不支持的 `"doc"`。
- 检查会抛出 `UnsupportedFileTypeError`。
- 同时确认错误信息里带上原始类型，方便定位问题。

`test_infer_file_type_rejects_unknown_filename_extension`

- 不传 `file_type`。
- 给文件对象一个 `.txt` 文件名。
- 检查函数会拒绝未知后缀并抛出 `UnsupportedFileTypeError`。

`test_infer_file_type_requires_recognizable_type_or_filename`

- 既不传 `file_type`，也不给可识别的文件名。
- 检查函数会报出“无法确定文件类型”的错误。

## 为什么有它

`document_processor` 的后续分发和 route 层都依赖文件类型推断结果。这个测试文件先把“显式类型优先、后缀推断兜底、异常场景明确报错”这些基本契约钉住，后面补具体处理器时不容易把入口行为带偏。

## 怎么跑

```bash
conda activate agent-gate
python -m pytest tests/document_processor/test_types.py -q
```
