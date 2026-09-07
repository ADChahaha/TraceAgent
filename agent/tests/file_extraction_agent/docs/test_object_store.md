# test_object_store.md

对应测试文件：`tests/file_extraction_agent/test_object_store.py`

## 验证内容

验证 agent 侧统一对象存储接口（S3 语义）及 boto3 实现 `S3ObjectStore`，以及
`s3://` URL 的解析。所有业务读写都应通过这个统一接口，而不是直接访问存储实现。

## 实现思路

- `ObjectStore`：S3 语义协议（create_bucket / put_object / get_object /
  head_object / delete_object / list_objects）。
- `S3ObjectStore`：通过 boto3 访问 storage 服务（endpoint 由环境变量配置）。
- `parse_resource_path("s3://<bucket>[/<key>]")`：解析出 bucket 和 key；
  非 `s3://` 前缀抛 ValueError。
- `build_s3_object_store()`：按 `S3_ENDPOINT_URL` / `S3_BUCKET_PREFIX` 环境变量构造。

## 测试函数

| 函数 | 验证内容 |
| --- | --- |
| `test_parse_resource_path_root` | `s3://res_abc` 解析出 bucket=res_abc，key 为空。 |
| `test_parse_resource_path_with_key` | `s3://res_abc/documents/01/a.md` 解析出 bucket 和 key。 |
| `test_parse_resource_path_rejects_non_s3` | 非 s3:// 前缀抛 ValueError。 |
| `test_s3_object_store_interface_shape` | S3ObjectStore 具备接口要求的全部方法。 |
| `test_s3_object_store_bucket_prefix` | 桶名前缀拼接正确。 |
| `test_build_s3_object_store_uses_env` | 环境变量正确注入 endpoint 与前缀。 |