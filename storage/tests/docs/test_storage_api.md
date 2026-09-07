# test_storage_api.md

对应测试文件：`tests/test_storage_api.py`

## 验证内容

验证 storage 服务（本地 S3 兼容对象存储 HTTP 服务）的核心端点行为。测试**用 boto3
作为真实客户端**连接一个在进程内启动的 storage 服务，确保标准 S3 客户端能正常工作。

## 实现思路

```text
测试 fixture 启动 uvicorn（storage.main.create_app）在随机端口
  -> 创建 boto3 client，endpoint_url 指向该端口
  -> 用 boto3 的 create_bucket/put_object/get_object/head_object/
     delete_object/list_objects_v2 验证
```

- storage 服务返回标准 S3 wire 协议：XML 列表、ETag、Content-Length，
  boto3 才能正确解析。
- 数据落在 `create_app(data_root=tmp_path)` 指定的临时根目录，测试结束自动清理。

## 测试函数

| 函数 | 验证内容 |
| --- | --- |
| `test_put_and_get_object_roundtrip` | boto3 写入对象再读回，内容一致。 |
| `test_head_object_returns_metadata` | head_object 返回对象大小。 |
| `test_head_missing_raises` | HEAD 不存在的对象抛异常。 |
| `test_get_missing_raises` | GET 不存在的对象抛异常。 |
| `test_delete_object` | DELETE 后对象不可再读。 |
| `test_list_objects_v2_with_prefix` | 按前缀列出对象，只返回匹配 key。 |
| `test_data_lands_under_data_root` | 数据实际落在数据根目录下的桶子目录中。 |