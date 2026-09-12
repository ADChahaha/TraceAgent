# Backend

backend 用 SessionManager 管理多轮会话，通过独立 agent 的 gRPC 服务执行任务。浏览器关闭后任务继续；GET /resume 读取数据库历史、合并当前轮快照并订阅后续事件。

```text
问题与可选文件 → POST /chat/completion → manager 创建 turn
  → PrepareResources（有新文件时）→ ChatCompletion → 事件落库 → SSE
重新打开 → GET /resume → 历史与当前轮快照 → 后续 SSE
用户取消 → POST /cancel → 本地终态 → 原 gRPC call.cancel()
```

## 运行

从仓库根目录运行：

```powershell
python -m pip install -e ./agent_proto -e "./backend[dev]"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

独立启动 agent，默认 gRPC 地址 127.0.0.1:8001。一个 backend worker 保证每个 session 唯一 owner；进程重启会将遗留活跃轮标为失败。

| 环境变量 | 默认值 |
| --- | --- |
| BACKEND_DATABASE_PATH | backend/backend.sqlite3 |
| AGENT_SERVICE_TARGET | 127.0.0.1:8001 |
| AGENT_SERVICE_TIMEOUT_SECONDS | 1200 |
| AGENT_GRPC_MAX_MESSAGE_BYTES | 67108864 |

队列、上传和回收参数通过 BackendSettings 配置。旧 AGENT_SERVICE_CANCEL_TIMEOUT_SECONDS 字段保留，但原 call.cancel() 不使用独立取消 RPC 超时。

## 接口与验证

执行接口为 POST /chat/completion、GET /resume、POST /cancel，另保留 GET /healthz、GET /capabilities。旧 /qa/tasks 已移除，前端需要迁移。

```powershell
python -m pytest backend/tests -q
```

[设计](docs/DESIGN.md) · [接口](docs/API.md) · [恢复机制](docs/SESSION_MANAGER.md) · [数据表](docs/table.md)

当前面向单用户本地服务，没有租户鉴权。数据库初始化不迁移旧 qa_* 数据。
