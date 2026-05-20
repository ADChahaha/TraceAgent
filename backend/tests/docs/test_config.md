# `test_config.py`

这组测试覆盖 `backend` 的配置和接口边界，重点验证 task spec 不写死在 Python 代码里，也不暴露内置实验数据源。

## 测试链路

```text
BackendSettings(...)
  -> 只管理数据库、agent service 地址和支持文件类型
  -> 不创建 task_specs / task_specs_dir 属性
  -> POST /tasks 必须从请求表单接收 task_spec
FastAPI app 启动
  -> 只挂任务和能力接口
  -> 路由表中不注册 /experiments/... 这类内置实验接口
  -> 路由表中不注册旧人工检查接口
  -> 数据库初始化会清理旧 route/review schema 残留，避免本地旧库继续暴露 route 列或旧人工复核表
  -> 访问历史实验路径时只能得到 404
```

## 测试函数

- `test_backend_settings_does_not_define_builtin_task_specs`：验证 `BackendSettings` 不暴露内置 task specs 或默认 task spec 目录，避免 backend 对具体业务字段 schema 做兜底。
- `test_backend_does_not_register_builtin_experiment_routes`：验证 backend 路由表不再注册 `/experiments/...` 内置实验接口，避免缺数据时返回 404 却仍然暴露实验 route 的假阳性。
- `test_backend_does_not_register_manual_check_routes`：验证 backend 路由表不再注册旧人工检查接口，避免删除 route 功能后仍能从 HTTP 层进入人工审核流程。
- `test_database_initialization_removes_legacy_route_and_review_schema`：验证启动初始化遇到旧 SQLite schema 时，会移除 `tasks.route/route_reason`、`field_commits` 的旧 review/route 列，以及 `field_routes/reviews/review_fields` 旧表。
