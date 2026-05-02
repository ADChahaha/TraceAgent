# `test_integration.py`

## 基本实现思路

这个测试文件从公开入口 `service.document_processor.processor.process(...)` 验证真实 PDF fixture 的入口链路。为避免测试依赖网络下载 OCR 模型，测试读取真实 PDF bytes，但用 fake docling 转换函数替代实际模型推理。

```text
真实 PDF fixture
  -> process(file_obj)
  -> 真实入口校验、文件名解析和 bytes 读取
  -> fake convert_to_docling_document(...)
  -> fake export_html(...)
  -> clean_semantic_html(...)
  -> ProcessResult(filename, html)
```

## 测什么

- 公开入口能接收真实 PDF 文件对象。
- 返回文件名是源 PDF 基名。
- 读取到的源 bytes 确实是 PDF。
- 返回结构只包含清理后的 HTML fragment 契约。

## 每个函数在干什么

`test_process_handles_real_pdf_fixture_via_public_interface`

- 打开真实 PDF fixture。
- 替换 docling 转换和 HTML 导出函数。
- 调用公开入口 `process(...)`。
- 检查文件名、PDF bytes 前缀和 HTML 返回值。

## 怎么跑

```bash
conda activate agent-gate
python -m pytest tests/document_processor/test_integration.py -q
```
