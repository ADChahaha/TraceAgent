# `test_document_client.py`

该测试文件验证 backend 与独立 document service 之间的 gRPC 边界。

- `test_document_client_calls_document_resource_service`：验证上传文件、session_id 和待删除 raw 引用被映射到 `DocumentResourceService.PrepareResources`，并正确解析资源引用。
- `test_document_client_maps_grpc_errors`：验证 document service 的 gRPC 错误转换为 backend 的 `DocumentServiceError`。
