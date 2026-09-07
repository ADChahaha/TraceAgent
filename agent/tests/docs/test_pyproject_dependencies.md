# test_pyproject_dependencies.py

这组测试固定 `agent/pyproject.toml` 的直接依赖声明，避免源码已经直接 import 的第三方包只靠传递依赖被安装。

实现链路：

```text
agent/pyproject.toml
  -> tomllib 读取 project.dependencies 和 project.optional-dependencies.dev
  -> 从 PEP 508 依赖字符串中提取 package name
  -> 校验运行时直接 import 的包在 dependencies 中
  -> 校验测试入口需要的包在 dev optional dependencies 中
```

## 测试函数

- `test_agent_pyproject_declares_direct_runtime_dependencies`：显式声明 grpcio、protobuf、标准探活及原业务依赖，移除 agent 的 HTTP 服务直接依赖。
- `test_agent_pyproject_declares_direct_test_dependencies`：声明 grpcio-tools 与 pytest，确保协议生成校验和 RPC 测试可在开发环境运行。
