# document_processor 关键决策

归属 [Document Processor 设计](DESIGN.md)，记录单文件文档解析模块的长期边界取舍。

## 1. 按格式拆分独立解析子包，只输出标准化 HTML

- 决定：`document_processor` 仅支持 PDF（`pdf/` 经 MinerU）与 DOCX（`docx/` 经 `python-docx`），统一输出可供建树与预览的完整 HTML；不抽取业务字段，不支持旧版 `.doc`，不暴露独立网络入口，不负责资源发布。
- 原因：不同格式解析管线差异大，保持按格式独立子包便于后续按"面向增加"方式扩展新文档类型，同时让解析层保持纯输入输出边界。
- 排除：在解析模块中耦合字段抽取、向量索引或对象存储发布逻辑。
