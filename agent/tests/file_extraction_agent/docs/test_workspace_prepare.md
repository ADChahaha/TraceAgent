# test_workspace_prepare.py

验证 prepare 子进程产物（workspace payload）的内容与还原：父进程只保存这份数据，工具子进程据此重建文档树。

## 实现链路

```text
load_workspace_payload(resource_refs)
  -> 解析 documents/index 定位并校验同 bucket
  -> GET documents.zip -> 校验 zip -> 加载并校验 manifest/index/vectors
  -> {bucket, documents_archive_b64, index:{model_id, dimension, chunks, vectors_b64}}

document_tree_from_payload(payload)
  -> base64 解码归档 -> ArchiveObjectStore -> DocumentFileTree
  -> 只读工具不再访问 storage 服务

index_to_payload(index)
  -> chunks asdict + 向量转 little-endian float32 + base64
```

## 测试函数

- `test_prepare_payload_contains_archive_and_resolved_index`：payload 含可解压归档、模型维度信息和已解析为 `documents/...` 的 covered_files。
- `test_document_tree_from_payload_reads_without_storage`：只用 payload 就能浏览并读取 Markdown 正文。
- `test_index_to_payload_preserves_vectors`：向量经 payload 序列化后按原字节还原，chunks 顺序不变。
