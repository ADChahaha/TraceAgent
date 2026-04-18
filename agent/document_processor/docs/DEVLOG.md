# 开发日志 (DEVLOG)

最后更新：2026-04-19

## 2026-04-19 02:19:34

- 完成：仓库根 `README.md` 新增 Quickstart，明确使用者先在本地创建并启用 `agent-gate` 环境，再按子项目安装依赖
- 完成：`agent/README.md` 改写为面向使用者的入口文档，收敛为 Overview、Quick Start、Usage 和模块说明
- 完成：README 示例路径改为相对路径，避免把个人机器绝对路径写进用户文档

## 2026-04-19

- 完成：将原 `ocr_processor` 整体重命名为 `document_processor`，统一模块命名、导入路径和公开入口，避免继续用“OCR”误导真实职责
- 完成：保留并明确公共业务入口为 `document_processor.processor.process(file_obj, file_type=None)`，由 `ProcessorDispatcher` 统一分发到 PDF 和 DOCX 处理链路
- 完成：保留 `schemas.py`、`types.py`、`impl/dispatcher.py`、`impl/doc/`、`impl/pdf/`、`impl/docling_blocks.py`、`impl/markdown_export.py` 这套分层，并整体迁移到新包名下
- 完成：包根目录只导出稳定公共接口；`DocProcessor`、`PdfProcessor` 改为按需懒加载，减少调用方无关依赖的初始化耦合
- 完成：新增 `agent/routes/document_processor.py` 作为 HTTP 适配层，并在 `agent/main.py` 与 `agent/routes/__init__.py` 中切换到新的 router 导出
- 完成：在 `agent/pyproject.toml` 中把打包对象从 `ocr_processor` 切换到 `document_processor`，同时补充 `file_extraction_agent.impl` 和任务规格文件的打包配置
- 完成：移除旧的 `agent/routes/ocr_processor.py` 与整套 `agent/ocr_processor/` 实现，避免新旧双轨并存
- 完成：测试目录从 `agent/tests/ocr_processor/` 迁移到 `agent/tests/document_processor/`，并同步更新 API 测试中的导入路径
- 完成：补充 `agent/tests/conftest.py` 与 `agent/tests/file_extraction/`，把文档标准化之后的字段抽取链路也纳入当前工程测试布局
- 完成：补齐 `README.md`、`docs/DESIGN.md`、`docs/DEVLOG.md` 的文档分工，其中 `README.md` 面向使用者，`DESIGN.md` 记录实现设计，`DEVLOG.md` 负责沉淀本轮迁移记录
- 当前进度：PDF 与 DOCX 主链路统一走 Docling；`.doc` 仍保持未实现状态，失败时直接向上抛错

## 2026-04-18

- 完成：补齐 `document_processor` 文档定位，明确这层负责文档标准化处理，不直接承担字段抽取
- 完成：统一业务入口为 `document_processor.processor.process(file_obj, file_type=None)`
- 完成：明确 route 层与业务层分离，HTTP 适配放在 `agent/routes/document_processor.py`
- 完成：将 `README.md` 收敛为用户使用说明，把实现分层和处理链路集中到 `docs/DESIGN.md`
- 当前进度：PDF 与 DOCX 主链路统一为 Docling；`.doc` 仍保持未实现状态
- 处理记录：包根目录只导出公共接口，`docling` 相关模块按需加载
- 处理记录：文档分工调整为 `README.md` 面向使用者、`docs/DESIGN.md` 面向开发者、`docs/DEVLOG.md` 记录最近变更
- 下一步：继续收敛 `README.md`、`DESIGN.md`、`DEVLOG.md` 的分工，避免内容重复
