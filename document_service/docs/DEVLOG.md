# Document Service Devlog

## 2026-09-20

### 补传只处理新文件并在启动时预热模型

上传原先下载、解析并编码全部 raw。现在只列旧文件名，解析新增或替换批次，读入已有产物并复用未变文档与向量，沿用原模型及分块配置，合并发布后再写 raw。backend 仍在处理完成后更新 DB，问答继续取 session 全部资源引用。新目录使用已有最大编号后的编号，旧引用不变；新旧 manifest 均支持。解析、embedding 或本地校验失败不写桶。生产启动先加载默认模型并做一次短文本编码，预热完成后才监听和报告 SERVING。

TDD 先确认补传读取旧 raw、embedding 失败留下新 raw、服务缺少预热入口而失败，再实现并通过。覆盖新增、替换加删除、新旧清单、空正文与索引维度、旧正文和向量逐项保持。文档服务全套及后端文件/文档客户端共 87 项测试通过。

通过临时 backend DB 调用实际 document gRPC、OpenVINO 模型和 storage，对同样的 4 个 DOCX 后追加第 5 个 DOCX 做单次前后测量：补传 0.613 秒降至 0.180 秒；首次 4 个文件为 0.695/0.612 秒。每个文件含 20 段测试文本，末尾核对索引含 5 个文档。此结果仅代表该合成样本；测试桶对象已清理，没有上传到用户会话。服务已重启，document 健康为 SERVING，指定 3000 会话页面返回 200。

仍使用会话级归档和索引，因此合并发布有读写成本；没有改为每文件独立资源包。逐对象发布或之后写 raw 失败仍无远端原子回滚。

## 2026-09-19

### 纯删除复用已发布文档和向量

Remove 原来先下载全部 raw，再解析剩余文件并重新 embedding。现在纯删除只列举 raw 名称，从既有归档和索引剔除目标文档及对应向量行，校验发布成功后再删除 raw。剩余路径、分块 ID、正文和向量保持不变，避免连续删除导致历史引用重编号。新清单保存文件到目录映射，旧清单首次裁剪时从编号恢复映射。未知目标幂等跳过，最后一个文件清空产物。上传仍全量重建；归档压缩和存储读写成本仍存在，逐对象发布仍没有远端原子回滚。

TDD 先确认删除触发 raw 下载而失败，再实现裁剪。覆盖新旧清单连续删除、正文与向量逐项保持、最后清空、批量与重复删除、损坏索引不修改资源，以及空正文文档无目录时的删除。文档服务 67 项、后端文件和文档客户端 14 项测试通过。未测量真实用户文件的耗时，也未重启当前运行的服务。

## 2026-09-16

### 解析失败毒化会话（孤儿 raw 卡死上传）

- 修复 PrepareResources 的写序：原来新 raw 在解析之前写入会话桶，解析失败留下桶内孤儿 raw；由于桶是事实来源且每次全量重建都重解析全部 raw，坏文件毒化同一会话的每一次后续上传（全部失败），而它不在 DB 资源表里、remove_file 够不到，会话上传功能永久卡死。
- 修复：解析提前到任何写桶操作之前（合并集在内存中先解析），失败时桶保持原状；解析通过后才执行删除/写入新 raw 与发布。发布阶段失败仍可能留下可解析的孤儿 raw，会在下一次成功调用合并自愈（非毒化，已写入设计文档）。
- TDD：应用层与 route 层各 1 个测试先行（旧实现下孤儿 raw 已进桶、后续上传被毒化）。document_service 62 项通过（60+2）。

### 已完成工作

- PrepareResources 落实 proto 契约：桶固定为 `res_<session_id>`，服务读取请求中的 `session_id` 与 `remove_raw`，不再忽略。
- 移除"每次调用新建随机桶"的实现；会话桶内 `raw/` 对象成为事实来源，上传按文件名覆盖合并，移除删除桶内对象并幂等跳过未知目标。
- 新增会话层入口 `prepare_session_resources`（application.py）：合并桶内 raw 与新批次、校验 remove_raw 的 type 与桶归属、剩余为空时清理已发布产物并返回空引用。
- `resources.prepare_resources` 改为 `publish_resources(store, bucket, documents)`：只负责在指定桶内构建发布 documents.zip/index/manifest，raw 增删归会话层。
- 空批次 + remove_raw 不再误报 INVALID_ARGUMENT（此前 backend 的 remove_file 对真实服务必然失败）；同一会话二次上传不再丢弃旧文件。
- 测试改为真实调用形状：route 测试以 `session_id` 驱动、覆盖空批次删除与跨桶/type 拒绝；agent 侧资源 fixture、边界与集成测试同步迁移到新 API。

### 已知问题（未在本任务处理）

- storage 的桶名校验可被 `"."` 绕过，且错误体非 S3 XML，boto3 客户端 `NoSuchKey` 分支永不触发（`get_object` 缺失对象抛 ClientError 而非返回 None）。
- backend 会话生命周期在事务写失败后没有恢复出口；`upload_files`/`remove_file` 的 document service 调用在命令队列外执行，存在并发读改写竞争。

## 2026-09-15

### 已完成工作

- 将 document processor、document resources、document gRPC 入口和相关测试从 agent 目录迁移到独立 `document_service/`。
- 将 S3-compatible ObjectStore 抽到共享 `traceagent_shared` 包，agent 与 document service 通过该包共享基础设施。
- document service wheel 只包含文档解析和资源发布模块；agent wheel 不再打包文档模块。
- 新增独立的 document service packaging、目录边界和跨服务 resource integration 测试。
