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

- `test_agent_pyproject_declares_direct_runtime_dependencies`：验证 `langchain-core`、`pydantic`、`starlette` 这些 agent 运行时代码直接 import 的包被显式写入 `project.dependencies`。
- `test_agent_pyproject_declares_direct_test_dependencies`：验证 `httpx` 和 `pytest` 写入 `project.optional-dependencies.dev`，保证 `fastapi.testclient` 相关测试在干净开发环境中可运行。
