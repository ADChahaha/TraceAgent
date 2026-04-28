# `test_integration.py`

## 基本实现思路

这个测试文件不直接碰 `impl/docx/processor.py` 或 `impl/pdf/processor.py`，而是专门从 `service.document_processor.processor.process(...)` 这个对外入口做真实样本集成验证。它固定的链路是：

```text
测试夹具目录里的真实 `.docx` / `.pdf` 文件
  -> 以二进制文件对象方式打开
  -> 调用 `service.document_processor.processor.process(file_obj)`
  -> 外层入口校验 `read()` 并按文件名推断 `FileType`
  -> `InternalProcessorInterface` 选择默认注册的 `DocxProcessor` / `PdfProcessor`
  -> 真实处理器完成解析
  -> 返回统一的 `ProcessResult`
```

这个文件的重点不是验证某个私有 helper，而是钉住“包对外公开接口能不能拿真实文件跑通”这件事。对外入口返回的 `filename` 也要求保持为可读的基名，例如 `实验报告-模板.docx` 或 `关于公布2025届校级优秀本科生毕业设计（论文）名单的通知.pdf`，而不是测试机上的绝对路径。

## 测什么

- `service.document_processor.processor.process(...)` 能处理真实 `DOCX` 样本
- `service.document_processor.processor.process(...)` 能处理真实 `PDF` 样本
- 对外入口返回的 `ProcessResult` 至少包含可用的 `markdown`、`md_list`、`blocks` 和基础 `meta_info`

## 每个函数在干什么

`test_process_handles_real_docx_fixture_via_public_interface`

- 从测试夹具目录打开真实的 `实验报告-模板.docx`。
- 不直接实例化 `DocxProcessor`，而是调用公开入口 `process(...)`。
- 检查返回类型、文件名、markdown 和 blocks 都是有效结果。

`test_process_handles_real_pdf_fixture_via_public_interface`

- 从测试夹具目录打开真实的 `关于公布2025届校级优秀本科生毕业设计（论文）名单的通知.pdf`。
- 不直接实例化 `PdfProcessor`，而是调用公开入口 `process(...)`。
- 检查返回类型、文件名、markdown、blocks 以及 PDF 特有的 `block_count/page_count` 元信息。

## 为什么有它

现有单元测试已经分别覆盖了入口分发、`DocxProcessor` 和 `PdfProcessor` 的局部行为，但还缺一个“真实文件 + 公开接口”的端到端检查。这个测试文件把那条公开链路固定住，后面如果默认注册、文件类型推断或真实处理器接线断了，这里会第一时间报出来。

## 怎么跑

```bash
conda activate agent-gate
python -m pytest tests/document_processor/test_integration.py -q
```
