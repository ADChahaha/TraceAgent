# test_archive_store.py

这份测试验证 zip 归档支撑的内存对象存储，以及按 key 前缀路由的组合存储。

## 实现链路

```text
ArchiveObjectStore(bucket, zip_bytes)
  -> 用 zipfile 在内存解析归档（不落盘），成员名即对象 key
  -> get_object / list_objects 只读归档成员

CompositeObjectStore(documents_store, default_store)
  -> key 以 documents/ 开头或等于 documents 时走归档
  -> 其余 key（如 index/*、manifest.json）走默认 S3 store
```

问答打开资源时，文档树来自 `documents.zip`，索引来自独立对象；两者共用一个组合 store，所以 `covered_files` 的存在性校验也能命中归档里的文档。

## 测试函数

- `test_archive_store_lists_and_reads_members_without_disk`：归档能按 key 读出成员、缺失 key 或不同 bucket 返回 `None`，`list_objects` 按前缀过滤，全程不落盘。
- `test_composite_store_routes_documents_to_archive_and_rest_to_default`：`documents/...` 走归档且不触碰默认 store；`index/vectors.npy` 走默认 store；`list_objects` 的前缀路由一致。
