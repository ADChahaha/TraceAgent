# 文档资源设计

本模块负责把解析后的 HTML 准备成可跨轮复用的资源，并发布到独立的 storage 服务。
gRPC 层通过 `PrepareResources` 串联文件解析与资源准备；问答接口只接收返回的资源定位数组。

```text
files（PDF / DOCX）
  -> route 校验全部文件类型，调用 document_processor.process
  -> prepare_resources(documents, raw_files) 在本机临时目录生成 Markdown 文件树并构建索引
  -> 校验临时产物（manifest/index/文档引用）
  -> 通过 S3ObjectStore（boto3）把整棵产物 + 原始文件 bytes 发布到 storage 服务
       bucket = res_*，key 为 documents/、index/、manifest.json、raw/<filename>
  -> 返回资源定位数组 [{type, location}]：
       documents -> s3://<bucket>/documents
       index     -> s3://<bucket>/index
       raw       -> s3://<bucket>/raw/<filename>（每个原始文件一项）
```

已发布资源由 Agent 工具经 storage 服务读取，本模块不提供消费端加载接口。

## 边界

- 本包对外只导出 `prepare_resources`；返回 `list[ResourceRef]`（强类型，type + location）。
- `documents.py` 负责 HTML 转文件（本地临时目录）；`index.py` 负责文档分块和索引构建；
  `model.py` 只供生成阶段加载模型与 tokenizer。
- `_validate_prepared` 只校验本次临时产物，成功后才发布到 storage；不提供消费端 `load_resource`。
  生成包不导入 Agent 工具。
- 两边遵守相同存储格式：manifest 版本 1，记录模型/后端；index/index.json 记录维度与 chunks，
  index/vectors.npy 保存归一化文档向量；covered_files 相对 documents 保存。
- 资源 bucket 名 `res_*`；每次准备生成独立 bucket，不使用 task_id 或 completion_id 作为标识。
  首版不做内容去重、自动过期或删除接口。
- `documents/` 是模型唯一可浏览的 key 前缀；`index/` 与 `manifest.json` 保存内部数据。
  索引引用使用相对文档路径。
- 清单固定 embedding 模型、后端及分块配置；查询沿用资源模型，不能因环境变量变化改用其他模型。
- 准备失败清理本次临时目录，不发布半成品；问答工具对无效资源抛 ValueError，不重新解析或构建索引。
- 资源与 completion 生命周期分离；问答完成、失败或取消均保留资源。

## 与 storage 服务的关系

`prepare_resources` 通过 `build_s3_object_store()`（boto3，endpoint 由 `S3_ENDPOINT_URL`
配置，默认 `http://localhost:9000`）写入 storage 服务。storage 服务与本包平级，
纯 Python 自写的 S3 兼容 HTTP 服务，底层本地目录落盘。

## 接口选择

PrepareResources 同步返回，调用方等待完整资源发布。内部解析与资源构建保持独立模块，
gRPC 调用方无需传输解析中间产物；backend 尚未适配新协议。
