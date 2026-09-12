# test_qa_task_flow.py

保留原测试文件路径，契约改为三个会话接口。通过 TestClient 或直接 ASGI 消息驱动请求，检查流首帧、恢复结果和断连时后台生命周期。

- `test_completion_and_resume_return_snapshot_without_cursor`：completion 发起、resume 恢复完成历史、不重复执行，不暴露 SSE 游标；取消终态幂等，校验错误和旧路由下线。
- `test_multipart_prepares_resource_references`：上传后资源引用送到 completion，非法文件在调用前拒绝。
- `test_http_disconnect_does_not_cancel_background_turn`：收到首帧后断开真实 ASGI 请求，后台继续消费并完成。
