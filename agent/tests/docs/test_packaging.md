# 安装包验证

源码 → 本地构建 wheel（不下载依赖）→ 读取包内容，验证迁移后的模块可随安装包发布。

- `test_wheel_contains_resource_and_qa_modules`：构建成功且包含新 HTTP 入口、资源模块、解析器和问答图，不包含已删除的解析 route。
