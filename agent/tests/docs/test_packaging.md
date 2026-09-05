# 安装包验证

源码复制到临时目录 → 本地构建 wheel（不下载依赖，不复用旧 build 产物）→ 读取包内容，验证迁移后的模块可随安装包发布。

- `test_wheel_contains_resource_and_qa_modules`：构建成功且包含新 HTTP 入口、资源模块、解析器、问答图及独立 embedding.py，不包含旧 embedding 包或已删除的解析 route。
