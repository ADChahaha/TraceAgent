# 开发日志 (DEVLOG)

最后更新：2026-04-18

## 2026-04-18

- 完成：补齐 `document_processor` 文档定位，明确这层负责文档标准化处理，不直接承担字段抽取
- 完成：统一业务入口为 `document_processor.processor.process(file_obj, file_type=None)`
- 完成：明确 route 层与业务层分离，HTTP 适配放在 `agent/routes/document_processor.py`
- 当前进度：PDF 主链路为 Docling；DOCX 为 Docling 优先、`python-docx` fallback
- 处理记录：包根目录只导出公共接口，`docling` 相关模块按需加载
- 下一步：继续收敛 `README.md`、`DESIGN.md`、`DEVLOG.md` 的分工，避免内容重复
