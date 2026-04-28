# `test_packaging.py`

## 基本实现思路

这份测试用静态方式约束 `agent/pyproject.toml` 的打包声明，避免源码目录下测试通过，但构建 wheel 后遗漏运行时子包。

```text
agent/pyproject.toml
  -> 读取 tool.setuptools.packages
  -> 确认 service 顶层包存在
  -> 确认 service.document_processor、service.file_extraction_agent 和 service.route_policy_agent 业务子包存在
  -> 确认 document_processor / file_extraction_agent 的 impl 子包也会进入 wheel
```

## 测什么

- `service` 会被打进 `agent-service` wheel。
- `service.document_processor`、`service.file_extraction_agent` 和 `service.route_policy_agent` 会作为 service 包下的业务阶段进入 wheel。
- `service.document_processor.impl` 和 `service.file_extraction_agent.impl` 也会被打进 wheel，确保安装后还能导入 PDF/DOCX 处理器、`impl.graph`、`impl.resolution` 等运行时模块。

## 每个函数在干什么

`test_pyproject_packages_service_business_subpackages`

- 读取 `agent/pyproject.toml`。
- 解析 `tool.setuptools.packages`。
- 确认包列表包含 `service` 和迁移后的三个业务子包。
- 确认需要运行时导入的 `impl` 子包也被声明打包。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_packaging.py -q
```
