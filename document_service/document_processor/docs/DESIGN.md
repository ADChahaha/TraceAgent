# Document Processor 设计

`document_service.document_processor` 将上传文档转换为可供问答 agent 建树与前端预览的完整 HTML 文档。模块仅处理 PDF 与 DOCX（不抽取业务字段，不支持旧版 `.doc`），并将两种结构差异较大的管线拆分为独立子包：PDF 经 MinerU/OCR，DOCX 经 `python-docx`。

document service 的 gRPC 入口为 `DocumentResourceService.PrepareResources`：先调用本模块 `processor.process(...)` 解析，再由同级 `document_resources` 生成 Markdown 文件树与 embedding 索引并返回资源路径。本模块不单独暴露网络入口。

```text
file_obj (+ 可选 file_type)
  -> processor.process -> validate_file_obj -> resolve_filename -> detect_file_type
     |- pdf  -> _process_pdf -> pdf.convert_pdf_to_html (engine="mineru-pipeline")
     \- docx -> _process_docx -> docx.convert_docx_to_html (engine="python-docx")
  -> ProcessResult(filename, html)
```

## 主题文档

- [入口与分流](design/entry-and-dispatch.md)：目录树、`processor.py` 公开入口、共享校验函数与引擎分流
- [PDF MinerU 管线](design/pdf-pipeline.md)：`pdf/converter.py` 配置、`pdf/html.py` 标题降级、确定性 ID 与表格处理
- [DOCX 管线](design/docx-pipeline.md)：`docx/docx_processor.py` 原始顺序遍历、标题样式与 `docx_bNNN` 输出

相关：[API.md](API.md) / [README.md](../README.md) / [document_service 设计](../../docs/DESIGN.md) / [document_resources 设计](../../document_resources/docs/DESIGN.md)
