# test_manager

业务依赖注入 application 层，统一调用 wire_stream；涉及线级断言时，通过 `wire_stream` 组合业务事件流与生产 protobuf 编码器，RPC 用例仍经过真实路由。

模型配置或类型化消息 → 模型装配与路由事件适配 → 验证 protobuf 字段、可见文本和工具调用配对。

- `test_runtime_yields_event_objects_with_sequence`：直接比较 protobuf 事件，验证启动确认、完整正文及终态的字段与序号。
- `test_route_streams_without_manager`：无需注册表即可输出完整编号事件流。
- `test_startup_events_only_acknowledge_without_reading_documents`：启动确认不读取或遍历文档。
- `test_stream_wraps_messages_and_pairs_same_name_calls`：同名工具按调用 ID 保留参数和成功失败结果。
- `test_route_outputs_protobuf_without_dictionary_boundary`：路由所有事件直接返回 CompletionEvent，不再输出字典。
- `test_normalize_model_config_loads_default_env_file`：从默认环境文件读取模型参数。
- `test_build_chat_model_builds_responses_transport_by_default`：默认构建 Responses 流式模型。
- `test_build_chat_model_builds_chat_completions_transport_when_configured`：显式配置可选择 Chat Completions。
- `test_build_chat_model_rejects_unknown_transport`：拒绝未知模型传输方式。
- `test_normalize_model_config_rejects_untyped_dict_input`：拒绝未类型化的配置字典。
- `test_qa_records_text_from_responses_api_content_blocks`：从 Responses 内容块提取可见文本。
- `test_qa_records_terminal_stop_message_as_final_answer`：终止消息标记为最终回答。
- `test_qa_records_model_message_content_and_tool_calls_without_reasoning`：保留文本和工具调用，不输出隐藏推理。

输出适配器位于 `routes/file_extraction_agent.py`；编码错误回传业务流处理终态。
