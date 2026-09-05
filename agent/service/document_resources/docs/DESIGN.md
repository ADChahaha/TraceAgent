# 文档资源设计

本模块负责把解析后的 HTML 准备成可跨轮复用的本机资源。HTTP 层将文件解析与资源准备合并为 `POST /v1/document-resources`；问答接口只接收返回的路径。

```text
files（PDF / DOCX）
  → route 校验全部文件类型，调用 document_processor.process
  → prepare_resources(documents) 在受管理根目录的临时目录生成 Markdown 文件树
  → 收集文档文本，按模型 tokenizer 分块，生成文档 embedding
  → 保存 index/index.json、index/vectors.npy 和 manifest.json
  → 原子发布资源目录，返回 resource_path 与 filename/html

已发布 resource_path
  → Agent tools/workspace.py 校验目录、浏览和读取文档
  → Agent tools/embedding.py 读取清单与索引，编码 query 并检索
  → 本模块不参与问答读取
```

## 边界

- 本包对外只导出 `prepare_resources`；`materialize_tree` 返回目录 Path，不返回问答访问器。
- `documents.py` 负责 HTML 转文件；`search.py` 负责文档分块和索引构建；`model.py` 只供生成阶段加载模型与 tokenizer。
- `_validate_prepared` 只校验本次临时产物，成功后才发布；不提供消费端 `load_resource`。生成包不导入 Agent 工具。
- 两边遵守相同磁盘格式：manifest 版本 1，记录模型/后端；index/index.json 记录维度与 chunks，index/vectors.npy 保存归一化文档向量；covered_files 相对 documents 保存。

- 资源根目录通过 `DOCUMENT_RESOURCES_ROOT` 配置，默认 `agent/data/resources`。backend 只保存并回传路径，不读取 agent 磁盘。
- 每次准备生成独立资源版本，不使用 task_id 或 completion_id 作为资源标识。首版不做内容去重、自动过期或删除接口。
- `documents/` 是模型唯一可浏览的目录；`index/` 与 `manifest.json` 保存内部数据。索引引用使用相对文档路径。
- 清单固定 embedding 模型、后端及分块配置；查询沿用资源模型，不能因环境变量变化改用其他模型。
- 准备失败清理本次临时目录，不发布半成品；问答工具对无效资源抛 ValueError，不重新解析或构建索引。
- 资源与 completion 生命周期分离；问答完成、失败或取消均保留资源。准备和问答需访问同一机器的资源目录。

## 接口选择

准备接口同步返回，backend 继续使用后台文档线程等待。内部解析与资源构建保持独立模块，HTTP 调用方无需传输解析中间产物。
