# test_title.md

对应测试文件：`tests/file_extraction_agent/test_title.py`

## 验证内容

验证会话标题清洗、消息构造、流式可见文本聚合与 `AgentService.GenerateTitle` gRPC 路由错误映射。

## 测试函数

- `test_sanitize_title_strips_markdown_quotes_and_noise`：验证去除引号、Markdown 符号、前缀标签、尾随标点与多行噪声。
- `test_sanitize_title_truncates_safely`：验证超长英文标题按安全长度与词边界截断。
- `test_build_title_messages_includes_question_and_limited_filenames`：验证消息结构包含首问并限制最多附带 5 个文件名提示。
- `test_generate_title_streams_visible_text_and_sanitizes`：验证通过 `astream` 跳过隐藏推理块、拼接可见文本并完成清洗。
- `test_generate_title_rejects_empty_question_and_empty_model_output`：验证空问题抛 `ValueError`，模型空输出抛 `RuntimeError`。
- `test_grpc_generate_title_route_success_and_validation`：启动真实进程内 gRPC 服务，验证 `GenerateTitle` 正常返回与空问题返回 `INVALID_ARGUMENT`。
