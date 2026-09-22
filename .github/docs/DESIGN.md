# CI 设计

CI 从仓库根目录安装并验证可独立运行的服务。`main` 的 push 和 pull request 触发工作流；Agent、backend、frontend 在各自的干净 runner 上验证，全部通过后才执行生产启动检查。

backend 安装本地 `agent_proto`、`shared` 和 `backend[dev]`，让 pip 直接解析仓库内共享包，不去公共索引寻找未发布的 `traceagent-*` 包。测试使用内存数据库，Agent 调用由测试替身替代。

Agent job 安装本地协议、共享包、storage，以及 Agent 和 document service 的 `dev,embeddings` 扩展。storage 提供真实 HTTP 测试夹具；embeddings 提供查询编码器和文档服务启动预热所需的 OpenVINO 运行时。OCR 导入检查直接引用 `document_service.document_processor`，随后检查 MinerU CLI，再执行三个 Python 包和 CI 配置的回归测试。配置测试使用显式安装的 PyYAML 读取 workflow。任一步安装、导入或测试失败都会终止该 job。

frontend 使用锁文件安装依赖并执行测试。生产启动检查复用 `scripts/install.sh` 和 `scripts/start.sh`，使用占位模型 API 配置启动服务，通过两个 gRPC Health 和 backend/frontend HTTP 探活确认就绪，退出时清理子进程。文档服务预热仍使用真实 embedding 模型，冷环境首次执行需要下载模型。

普通 CLI 回归在子进程中替换 embedding 模型，并显式使用空缓存和离线模式；真实 CLI 模块、参数解析、模型预热调用和 gRPC 探活保持执行，保证服务生命周期测试不依赖模型仓库或本机凭据。
