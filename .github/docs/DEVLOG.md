# CI 开发日志

## 2026-11-25

`deployment-smoke` 原先在临时 `.env` 中写入 `BACKEND_DATABASE_PATH=:memory:`，导致 `uvicorn backend.main:app` 启动恢复在工作线程打开独立空内存库并报 `no such table: chat_sessions`。现改为使用 runner 临时文件 `/tmp/traceagent-ci-backend.sqlite3`（启动前清理残留文件及 `-wal`/`-shm`），并在 `/healthz` 后增加 `/chat/sessions` 探活以直接覆盖 SQLite 跨线程查询；同时移除 `backend` 单测 job 中实际未生效的 `BACKEND_DATABASE_PATH: ":memory:"`，在 `.github/tests/test_ci.py` 补加配置门禁防止回退。

验证：`backend/tests`、`.github/tests`、`memory/tests`、`scripts/tests` 共 119 项通过，`python3 memory/dream_scan.py --audit` 清零；本机以 CI 同款临时文件路径启动真实 `uvicorn backend.main:app` 进程，`/healthz` 返回 `{"status":"ok"}`、`/chat/sessions` 返回 `{"sessions":[]}`。

## 2026-09-22

服务拆分后，backend job 仍只安装 `backend[dev]`，导致 pip 从公共索引寻找仓库内的 `traceagent-protocol` 并失败；OCR 检查仍导入已经移除的 `service.document_processor`。现补齐 backend 的本地共享包安装，转换器导入改为独立 document service 的路径。

Agent 测试使用真实 storage 服务，文档 CLI 还会预热默认 embedding 模型，因此同一 job 补装 storage 和两个服务的 embeddings 扩展。新增回归测试读取实际安装命令、检查本地依赖闭包和测试运行时，并在子进程执行 workflow 的转换器导入。修复前已复现缺少共享包、缺少 storage 和旧导入路径三个失败。

全量测试随后暴露文档 CLI 用例会真实访问 Hugging Face，本机无效凭据导致模型初始化失败，父进程只看到探活超时。该用例现用 runpy 执行真实 CLI 模块，在子进程注入 embedding 替身，要求空缓存和离线环境下仍能预热、探活并正常退出；生产服务预热和部署检查保持真实模型行为。

验证：在新建 Python 3.11 虚拟环境执行 workflow 原样 backend 安装和测试命令，96 项通过；激活 `agent-gate` 执行 Agent、document service、shared 和 CI 配置测试，299 项通过。workflow 的 OCR 导入、MinerU CLI 和全部 shell 步骤语法检查通过；Agent 安装命令以 `--dry-run --ignore-installed` 成功解析全套依赖。验证平台为本机 macOS，GitHub Ubuntu 工作流和完整生产启动检查尚待推送后运行。
