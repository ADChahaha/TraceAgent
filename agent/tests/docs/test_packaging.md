# 安装包验证

源码复制到临时目录 → 本地构建 wheel（不下载依赖，不复用旧 build 产物）→ 读取包内容，验证迁移后的模块可随安装包发布。

- `test_wheel_contains_resource_and_qa_modules`：构建成功且包含新 HTTP 入口、资源模块、解析器、问答图及独立 embedding.py，不包含旧 embedding 包或已删除的解析 route。

安装包还必须包含独立的 core/graph.py 建图模块与 completion_runtime.py 单轮运行时。

消息、模型调用和工具执行模块 messages.py、model_invocation.py、executor.py 也必须随 wheel 安装。

资源构建模块以 document_resources/index.py 打包，旧 search.py 不再出现在 wheel 中。
