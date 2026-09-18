# 启动与安装脚本测试

测试在临时目录复制脚本，用可记录参数和环境的进程替代 Python、pnpm，不安装依赖、不连接模型、不读写业务数据。

- `sandbox`：构造最小前端构建标记、独立环境文件和命令记录器。
- `test_install_includes_storage_and_embedding_dependencies`：执行安装脚本，确认安装 storage，以及 agent 和 document service 的 embeddings 扩展依赖。
- `test_start_propagates_storage_endpoint_and_cleans_up`：分别验证默认本地 storage 和显式外部 S3 地址。本地模式必须先用应用工厂启动 storage 并采用配置端口；外部模式不能另启 storage。所有服务继承同一 endpoint，停止脚本后不遗留记录到的服务进程。

运行：激活 `agent-gate` 后，在仓库根目录执行 `python -m pytest scripts/tests -q`。
