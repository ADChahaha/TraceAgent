# test_storage_api.md

对应测试文件：`tests/test_storage_api.py`

## 验证内容

验证 storage 服务（本地 S3 兼容对象存储 HTTP 服务）的核心端点行为与错误契约。
测试**用 boto3 作为真实客户端**连接一个在进程内启动的 storage 服务，确保标准
S3 客户端能正常工作并按错误码分支。

## 实现思路

```text
测试 fixture 启动 uvicorn（storage.main.create_app）在随机端口
  -> yield SimpleNamespace(client=boto3 client, endpoint=端口 URL)
  -> 常规读写用 boto3 验证；错误码与 "." 桶绕过用绕过代理的 urllib 裸请求验证
```

- storage 服务返回标准 S3 wire 协议：XML 列表、ETag、Content-Length、
  XML Error 结构（`<Error><Code>...</Code></Error>`），boto3 才能解析出
  NoSuchKey 等错误码并分支。
- 数据落在 `create_app(data_root=tmp_path)` 指定的临时根目录，测试结束自动清理。

## 测试函数

| 函数 | 验证内容 |
| --- | --- |
| `test_put_and_get_object_roundtrip` | boto3 写入对象再读回，内容一致。 |
| `test_head_object_returns_metadata` | head_object 返回对象大小。 |
| `test_head_missing_raises` | HEAD 不存在的对象抛异常。 |
| `test_get_missing_raises_no_such_key` | GET 不存在对象抛 `NoSuchKey`（而非通用 404 ClientError），错误码可被 botocore 解析。 |
| `test_missing_object_error_body_is_s3_xml` | 缺失对象的 404 响应体是含 `<Code>NoSuchKey</Code>` 的 S3 XML。 |
| `test_delete_object` | DELETE 后对象不可再读。 |
| `test_list_objects_v2_with_prefix` | 按前缀列出对象，只返回匹配 key。 |
| `test_data_lands_under_data_root` | 数据实际落在数据根目录下的桶子目录中。 |
| `test_dot_bucket_rejected_across_operations` | 桶名 `.` 在建桶、读、写、列、删上全部返回 400 InvalidBucketName，跨桶对象原样保留。 |
| `test_dot_bucket_list_does_not_enumerate_other_buckets` | 以 `.` 列举返回 400，不得枚举其他桶的对象。 |
