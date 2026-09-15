# `test_packaging.py`

验证 document service wheel 的发布边界。

- `test_wheel_contains_document_service_only`：构建临时 wheel，确认解析器、资源构建和入口进入发布包，agent 的 `service/` 与 `routes/` 业务代码不会被打包。
