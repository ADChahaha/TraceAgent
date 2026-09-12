# 问答资源 fixture

`resource_path` 将测试 HTML 交给真实资源准备流程，注入三维向量替身和字符 tokenizer，把产物发布到测试专用 storage 服务（session 级 `storage_server` fixture 在随机端口启动），返回资源定位数组 `[{type, location}]`。每个测试隔离目录和配置，不加载真实 embedding 模型。

共享 `storage_server`（session 级）与 `s3_store` fixture 位于 `tests/conftest.py`：前者启动真实 storage 服务并把 `S3_ENDPOINT_URL`/`S3_BUCKET_PREFIX` 指向它；后者返回指向该服务的 `S3ObjectStore`。`resource_bucket(refs)` 从定位数组解析出 documents 的 bucket。

embedding 替身同时提供 encode 与 tokenize，资源构建复用同一个实例，不再注入独立 get_tokenizer。
