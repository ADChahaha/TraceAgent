# 业务入口测试

普通 Python 参数 → application 校验并预检资源 → 输出类型化事件 → 关闭内层执行流。

- `test_application_prepares_before_emitting_and_closes`：首事件前完成资源预检，输出不依赖 protobuf，提前关闭时释放 core 流。
- `test_invalid_request_never_prepares`：非法 ID 或空消息在资源预检前抛 ValueError。
- `test_service_rejects_invalid_json_without_transport`：直接消费业务事件时，嵌套 NaN、Infinity 或非 JSON 对象均产生唯一失败终态并关闭 core。
