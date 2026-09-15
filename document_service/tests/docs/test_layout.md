# `test_layout.py`

验证文档服务已经成为独立顶层目录，并且导入 document service 入口不会加载 agent 的问答业务包。

- `test_document_service_owns_processing_and_resource_modules`：验证入口、解析器、资源构建模块都在 `document_service/`，原 `agent/service/` 文档目录已移除。
- `test_document_service_imports_without_agent_business_package`：验证 document service 的启动依赖不反向导入问答 agent。
