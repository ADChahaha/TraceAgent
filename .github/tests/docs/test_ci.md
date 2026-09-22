# CI 配置回归测试

从真实 workflow 读取各 job 的安装命令和 OCR 导入语句，验证服务拆分后的依赖边界。测试使用 pytest 与 PyYAML，不下载模型、不连接外部服务。

- `editable_packages`：解析安装步骤中的 editable 参数，读取各包的真实项目名和 extras。
- `test_install_includes_local_dependency_closure`：分别检查 backend 和 Agent job，要求已安装包声明的仓库内依赖也从本地安装，避免 pip 去公共索引寻找未发布包。
- `test_agent_install_supports_storage_fixtures_and_embedding_startup`：要求 Agent job 安装测试夹具使用的 storage，以及查询编码器和文档 CLI 预热需要的 embeddings 扩展。
- `test_ocr_smoke_imports_current_converter`：抽取 workflow 的转换器导入，在子进程实际执行并检查默认语言，捕获模块移动后残留的旧路径。

运行：激活 `agent-gate` 后，在仓库根目录执行 `python -m pytest .github/tests -q`。
