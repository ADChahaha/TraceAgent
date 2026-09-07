# 安装包验证

分别复制 agent 与根目录 agent_proto 到临时目录 → 独立构建 wheel（不下载依赖）→ 验证业务包引用共享包、共享包独立导入 → 从仓库根目录重新生成并比对协议绑定。

- `test_wheel_contains_resource_and_qa_modules`：agent wheel 包含业务模块，声明 traceagent-protocol 依赖，不再打包共享协议副本。
- `test_generated_protocol_matches_source`：从仓库根目录的 agent_proto/agent.proto 重新生成绑定，逐文件确认提交产物与协议源同步。
- `test_shared_protocol_wheel_is_independent`：与 agent 同级的共享包可独立构建和导入，包含协议及生成绑定，不包含或依赖 agent 业务代码，后端可独立安装。

安装包还必须包含独立的 core/graph.py 建图模块与 completion_runtime.py 单轮运行时。

消息、模型调用和工具执行模块 messages.py、model_invocation.py、executor.py 也必须随 wheel 安装。

资源构建模块以 document_resources/index.py 打包，旧 search.py 不再出现在 wheel 中。
