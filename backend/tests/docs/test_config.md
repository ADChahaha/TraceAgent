# `test_config.py`

这组测试覆盖 `backend` 的配置边界，重点验证 task spec 不写死在 Python 代码里，也不通过默认目录兜底。

## 测试链路

```text
BackendSettings(...)
  -> 只管理数据库、agent service 地址和支持文件类型
  -> 不创建 task_specs / task_specs_dir 属性
  -> POST /tasks 必须从请求表单接收 task_spec
```

## 测试函数

- `test_backend_settings_does_not_define_builtin_task_specs`：验证 `BackendSettings` 不暴露内置 task specs 或默认 task spec 目录，避免 backend 对具体业务字段 schema 做兜底。
