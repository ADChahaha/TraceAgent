# 文档资源设计

本包负责会话文档资源的生产与删除裁剪，RPC 入口调用 `application.prepare_session_resources`，桶固定为 `res_<session_id>`。backend 保存返回的全量 ResourceRef；agent 只消费归档与索引，不重新解析文档。

## 上传构建

输入文件名与 bytes，以及可选 remove_raw。application 校验会话、文件名与引用归属，只列举桶内 raw 名称确定剩余文件；仅上传且未被删除的批次交给 document_processor 解析成 HTML。

首次上传直接构建；补传时 `resources.publish_resources(incremental=True)` 读入并校验既有归档、索引和清单。沿用已有模型、后端和分块配置，剔除被替换或删除文档的目录及向量行，只对新批次分块和 embedding，再拼接未变的旧向量。新文档目录从已有最大编号之后分配；未修改文档的路径、正文、chunk_id 与向量不变。空正文无向量的情况按实际非空索引维度合并。

校验与发布成功后才写新 raw、删除目标 raw，并返回全部资源引用。backend 在处理完成后更新 DB；每轮 agent 调用从 DB 读取 session 全部资源引用。解析、embedding 或本地校验失败不改变桶；逐对象发布或后续 raw 写入失败仍没有远端回滚。已有产物损坏时拒绝补传，不静默重算。

`documents.py` 负责 HTML 到编号目录与 Markdown；`index.py` 负责 tokenizer 分块及向量构建；`model.py` 按 model_id/backend 缓存模型，分块与编码复用同一个模型实例。生成包不导入 agent。

## 纯删除

只有 remove_raw 时，application 只列举 raw 名称，不下载原文件。存在剩余文件且目标确实存在时，`resources.remove_published_documents` 读取既有归档、清单和索引，在临时目录校验，按文件到目录映射移除目标文档、对应 chunks 和 vectors 行，再次校验后发布。剩余正文、路径、chunk_id 和向量原样保留，不调用解析、tokenizer 或 embedding。

manifest 的 `document_roots` 映射原文件名到一级文档目录。旧清单没有此字段时，按 documents 数组顺序与目录数字前缀恢复，首次裁剪后保存映射，连续删除时保留编号空缺。无法恢复映射或索引损坏时抛 ValueError，不回退到全量解析。未知目标幂等跳过；最后一个文件删除时直接清空产物并返回 []。

成功发布裁剪结果后 application 才删除目标 raw，返回 documents/index 及剩余 raw 的全量引用。构建或校验失败不写桶；发布中途失败仍可能留下部分产物，当前没有远端回滚或原子发布。同桶操作依赖 backend 串行化。

## 存储契约

通过共享 ObjectStore 写入独立 storage 服务，endpoint 由 `S3_ENDPOINT_URL` 配置。对象布局为：

- `documents.zip`：成员路径保留 `documents/...`，是 agent 唯一可浏览的文档树。
- `index/index.json`：模型 ID、维度和 chunks；covered_files 相对 documents。
- `index/vectors.npy`：与 chunks 顺序对应的归一化向量。
- `manifest.json`：版本 1、模型、后端、分块配置、原文件列表及可选 document_roots。
- `raw/<filename>`：原始文件，增删由 application 管理。

模型及分块配置随产物固定；删除沿用旧配置，不受当前环境变量影响。`_validate_prepared` 检查临时产物的清单、向量维度、数值和文档引用；不提供消费端加载接口。增量上传沿用旧配置；上传和删除均同步等待发布完成，资源在会话问答完成或取消后仍保留。
