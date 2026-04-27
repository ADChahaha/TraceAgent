# `test_processor.py`

## 基本实现思路

`document_processor.processor` 现在是对外统一入口，外部调用方只需要传入 `file_obj` 和可选的 `file_type`，不需要直接接触具体处理器类。外层入口自己负责输入校验和文件类型推断；真正的注册表和实例缓存都封装在 `impl/interface.py` 里的固定内部接口类 `InternalProcessorInterface` 中。外部入口把“已经确定好的 `FileType` + file_obj”交给这个内部类；内部类只负责根据类型从自己维护的注册表里找到具体处理器类，实例化后再走多态调用。外部不能显式注入处理器实例，扩展只能通过内部注册机制完成。

也就是说，这一层负责三件事：

1. 在 `impl/base.py` 里定义处理器基类，统一约束“处理器至少要会 `process(file_obj)` 并由子类实现 `_process(...)`”。
2. 在 `impl/interface.py` 里定义一个固定内部接口类，由它自己维护注册机制，把 `pdf/docx` 这类具体处理器和 `FileType` 绑定起来。
3. 暴露统一的 `process(...)` 入口，让外部不需要知道内部具体是哪一个处理器类在工作。

当前默认 `docx` 真实处理器位于 `impl/docx/processor.py`，目录名已经明确对应 `DOCX`，避免和老式 `.doc` 概念混淆。

## 测什么

- 基类会统一校验 file-like 输入并把真正处理逻辑委托给子类
- 基类会拒绝非 file-like 对象
- 顶层 `process(...)` 会按显式 `file_type` 路由到内部已注册处理器
- 顶层 `process(...)` 会在未传 `file_type` 时按文件名后缀推断，再路由到内部已注册处理器
- 顶层 `process(...)` 会拒绝非法输入
- 顶层 `process(...)` 会继续抛出不支持的文件类型错误
- 内部接口类的注册器会拒绝不是处理器子类的类
- `process(...)` 会通过内部接口类从注册表中取出已注册的处理器类并调用
- 默认 `docx` 处理器会真正调用 `docling` 生成 markdown 和 blocks
- `docling` 解析失败时不会走任何回退逻辑，而是直接把异常抛出来

## 每个函数在干什么

`test_document_processor_base_validates_file_like_input_and_delegates_to_subclass`

- 定义一个继承自 `BaseDocumentProcessor` 的 stub 子类。
- 调用基类的 `process(file_obj)`。
- 检查真正被调用的是子类的 `_process(...)`，说明基类负责统一入口，子类负责具体实现。

`test_document_processor_base_rejects_non_file_like_input`

- 定义一个最小子类。
- 传入普通 `object()`。
- 检查基类会先拦住非法输入并抛出 `InvalidFileObjectError`。

`test_process_routes_explicit_file_type_to_registered_processor`

- 手动把一个 `pdf` stub 处理器类注册进 `InternalProcessorInterface`。
- 显式传入 `file_type="pdf"`。
- 检查顶层 `process(...)` 会通过内部注册表找到它，并完成调用。

`test_process_uses_filename_inference_when_file_type_is_omitted`

- 构造一个 `.DOCX` 文件对象。
- 手动把一个 `docx` stub 处理器类注册进 `InternalProcessorInterface`。
- 不显式传 `file_type`。
- 检查顶层 `process(...)` 会先做类型推断，再通过内部注册表找到 `docx` 处理器。

`test_process_rejects_objects_without_file_like_read_method`

- 直接调用顶层 `process(...)` 并传入普通对象。
- 检查统一入口会拒绝这种输入。

`test_process_propagates_unsupported_file_type_errors`

- 传入 `.txt` 文件。
- 检查类型推断阶段抛出的 `UnsupportedFileTypeError` 会继续向外传递。

`test_register_processor_rejects_non_processor_subclasses`

- 用内部接口类 `InternalProcessorInterface` 的注册器去注册一个并不继承 `BaseDocumentProcessor` 的类。
- 检查注册阶段就会报错，避免错误类型混进处理器注册表。

`test_process_uses_registered_processor_class_when_no_instance_is_injected`

- 手动把一个 `pdf` 处理器类注册进 `InternalProcessorInterface` 的内部注册表。
- 调用顶层 `process(...)`。
- 检查内部接口类会从自己的注册表里构造处理器实例并完成调用。

`test_process_docx_uses_docling_to_generate_markdown_and_blocks`

- 用真实 `.docx` 样本构造一个包含标题和两段正文的文件对象。
- 直接走默认 `docx` 处理链路。
- 检查返回结果里不再出现“未实现”的 warning，而是有真实 markdown、`md_list` 和按 docling 节点生成的 `blocks`。

`test_process_docx_propagates_docling_errors_without_fallback`

- 针对 `DocxProcessor._convert_with_docling(...)` 打桩，让它抛出异常。
- 调用顶层 `process(...)` 处理 `.docx`。
- 检查异常会直接向外传播，说明当前实现没有偷偷切换到其他解析方案。

## 为什么有它

这个测试文件把新的“外层编排入口 + `impl/` 固定接口类 + 抽象基类 + 注册表 + 多态入口”结构固定下来，并额外把 `DOCX` 默认实现已经切到 `docling`、且失败时不允许回退这两个约束钉住，确保后面继续补算法细节时不会把当前处理策略改松。

## 怎么跑

```bash
conda activate agent-gate
python -m pytest tests/document_processor/test_processor.py -q
```
