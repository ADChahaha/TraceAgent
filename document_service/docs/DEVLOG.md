# Document Service Devlog

## 2026-09-15

### 已完成工作

- 将 document processor、document resources、document gRPC 入口和相关测试从 agent 目录迁移到独立 `document_service/`。
- 将 S3-compatible ObjectStore 抽到共享 `traceagent_shared` 包，agent 与 document service 通过该包共享基础设施。
- document service wheel 只包含文档解析和资源发布模块；agent wheel 不再打包文档模块。
- 新增独立的 document service packaging、目录边界和跨服务 resource integration 测试。
