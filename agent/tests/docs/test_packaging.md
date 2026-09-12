# test_packaging

复制业务包与共享协议到临时目录 → 构建 wheel → 检查文件与依赖 → 重新生成绑定并验证共享协议独立导入。

- `test_wheel_contains_resource_and_qa_modules`：业务 wheel 包含路由事件适配和 core 模块，不再打包 turn_stream.py，保留共享协议依赖。
- `test_generated_protocol_matches_source`：从仓库根目录的 agent_proto/agent.proto 重新生成绑定，逐文件确认提交产物与协议源同步。
- `test_shared_protocol_wheel_is_independent`：与 agent 同级的共享包可独立构建和导入，包含协议及生成绑定，不包含或依赖 agent 业务代码，后端可独立安装。
