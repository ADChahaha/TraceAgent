# `test_packaging.py`

## 基本实现思路

这份测试用静态方式约束 `agent/pyproject.toml` 的打包声明，避免源码目录下测试通过，但构建 wheel 后遗漏运行时子包。

```text
agent/pyproject.toml + 已跟踪集成脚本
  -> 读取 tool.setuptools.packages
  -> 确认 service 顶层包存在
  -> 确认 service.document_processor、service.file_extraction_agent 和 service.route_policy_agent 业务子包存在
  -> 确认 file_extraction_agent 的 impl/broad、impl/resolution、impl/tools 子包也会进入 wheel
  -> 确认集成脚本也使用 service.* 业务包路径和当前 .env 位置
```

## 测什么

- `service` 会被打进 `agent-service` wheel。
- `service.document_processor`、`service.file_extraction_agent` 和 `service.route_policy_agent` 会作为 service 包下的业务阶段进入 wheel。
- `service.document_processor.impl`、`service.file_extraction_agent.impl`、`impl.broad`、`impl.resolution` 和 `impl.tools` 也会被打进 wheel，确保安装后还能导入 PDF/DOCX 处理器、graph、runner 和工具模块。
- 已跟踪的文明寝室集成脚本不再导入旧的 `document_processor` / `file_extraction_agent` 顶层包，而是导入当前设计里的 `service.*` 包。

## 每个函数在干什么

`test_pyproject_packages_service_business_subpackages`

- 读取 `agent/pyproject.toml`。
- 解析 `tool.setuptools.packages`。
- 确认包列表包含 `service` 和迁移后的三个业务子包。
- 确认需要运行时导入的 `impl`、`impl.broad`、`impl.resolution` 和 `impl.tools` 子包也被声明打包。

`test_tracked_integration_script_imports_service_business_packages`

- 读取 `agent/output/integration_civilized_dormitory/run_civilized_dormitory_e2e.py`。
- 确认脚本从 `service.document_processor` 和 `service.file_extraction_agent` 导入当前业务入口。
- 确认脚本不再引用旧顶层包路径或旧的 `.env` 路径。

## 怎么跑

```bash
conda activate agent-gate
cd agent
python -m pytest tests/file_extraction_agent/test_packaging.py -q
```
