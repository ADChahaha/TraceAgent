# `test_packaging.py`

## 基本实现思路

这份测试用静态方式约束 `agent/pyproject.toml` 的打包声明，避免源码目录下测试通过，但构建 wheel 后遗漏运行时子包。

```text
agent/pyproject.toml
  -> 读取 tool.setuptools.packages
  -> 确认 file_extraction_agent 顶层包存在
  -> 确认 file_extraction_agent.impl 子包也会进入 wheel
```

## 测什么

- `file_extraction_agent` 会被打进 `agent-service` wheel。
- `file_extraction_agent.impl` 也会被打进 wheel，确保安装后还能导入 `impl.graph`、`impl.resolution` 等运行时模块。

## 每个函数在干什么

`test_pyproject_packages_file_extraction_agent_impl_subpackage`

- 读取 `agent/pyproject.toml`。
- 解析 `tool.setuptools.packages`。
- 确认包列表同时包含 `file_extraction_agent` 和 `file_extraction_agent.impl`。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_packaging.py -q
```
