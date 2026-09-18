# Storage 设计

## 目标

`storage` 是一个本地、纯 Python 的 S3 兼容对象存储 HTTP 服务，与 `agent`、`backend`
平级。它让 agent（以及将来 backend）用统一的 S3 语义（bucket + key）存取文件，
底层实际落在本地目录。将来切换到真 S3/MinIO 时，调用方只改 endpoint，业务代码不变。

## 工作原理

```text
HTTP 请求
  -> FastAPI 路由（storage/main.py）
  -> DirectoryObjectStore（storage/core/object_store.py）
  -> 本地目录：数据根/storage/data 下，一个 bucket = 一个子目录，key = 桶内相对路径
```

端点与 S3 语义对应（响应遵循 S3 wire 协议，boto3 可直接访问）：

```text
PUT    /{bucket}/{key}            -> put_object（写入/覆盖，返回 ETag）
PUT    /{bucket}                  -> create_bucket（建桶）
GET    /{bucket}/{key}            -> get_object（读取 bytes）
HEAD   /{bucket}/{key}            -> head_object（Content-Length 元信息）
DELETE /{bucket}/{key}            -> delete_object（删除）
GET    /{bucket}?list-type=2&prefix= -> list_objects_v2（XML 列表）
GET    /healthz                   -> 探活
```

安全边界：

- bucket 名走白名单（小写字母/数字/下划线/连字符，1-63 字符，不含点号），由
  `DirectoryObjectStore._bucket_dir` 统一校验；拼接后还校验解析结果必须是数据根
  的直接子级，`"."`、`".."`、空名、带分隔符的名字全部拒绝，桶不可能解析到数据根。
- key 通过 `DirectoryObjectStore._obj_path` 校验：拒绝空串、`.`、绝对路径和
  `..` 逃逸（空 key 与 `.` 的 `Path.parts` 为空，会指向桶目录本身，同样拒绝）。
- 错误响应是 S3 XML Error 结构（`<Error><Code>...</Code></Error>`），boto3 按
  Code 分支：缺失对象抛 `NoSuchKey`，非法桶名抛 `InvalidBucketName`，非法 key
  抛 `InvalidKey`，读侧 `get_object` 的 None 语义由此成立。
- 本地开发不做签名鉴权；接入生产时再补 S3 Signature v4。

## 数据目录

- 默认数据根：`storage/data`（可由 `STORAGE_DATA_ROOT` 环境变量覆盖）。
- 独立启动：`python -m uvicorn storage.main:create_app --factory --host 127.0.0.1 --port 9000`。模块提供应用工厂，不提供全局 `app` 或命令行入口。
- 仓库 `scripts/start.sh` 默认先启动 storage，监听 `STORAGE_HOST` / `STORAGE_PORT`（默认 `127.0.0.1:9000`），再启动 agent、document service、backend 和 frontend。脚本将生成的 `S3_ENDPOINT_URL` 导出给子进程，使所有资源读写指向同一个服务。
- 已显式配置非空 `S3_ENDPOINT_URL` 时，脚本使用该外部服务，不启动本地 storage；外部服务由部署者管理。
- 脚本以 `exec` 启动服务，记录的 PID 就是服务进程，退出时统一终止并等待它们，不停止外部 storage。

## 与 agent 的关系

- agent 通过 `boto3`（endpoint 指向本服务）访问 storage。
- 资源定位数组 `[{type, location}]` 的 `location` 即 `s3://<bucket>[/<key>]`，
  agent 解析出 bucket/key 后经 storage 服务存取。
- storage 服务不 import agent 或 backend 的任何代码。

## 边界与限制

- 首版只实现对象存取，不做版本、副本、配额、加密。
- 单机本地目录，无跨节点共享。
