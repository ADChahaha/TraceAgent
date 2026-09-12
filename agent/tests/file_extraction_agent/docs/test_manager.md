# test_manager

模型配置或消息对象 → 本轮事件生成器 → 可见文本、工具结果与连续序号。

- `test_runtime_yields_event_objects_with_sequence`：运行时直接输出事件对象，传输编码由接口层负责。
- `test_completion_runtime_streams_without_manager`：无需注册表即可输出完整编号事件流。
- `test_startup_events_only_acknowledge_without_reading_documents`：启动确认不读取或遍历文档。
- `test_stream_wraps_messages_and_pairs_same_name_calls`：同名工具按调用 ID 保留参数和成功失败结果。
- `test_graph_keeps_events_as_objects_until_stream_boundary`：普通事件转换保持字典结构。
- `test_normalize_model_config_loads_default_env_file`：从默认环境文件读取模型参数。
- `test_build_chat_model_builds_responses_transport_by_default`：默认构建 Responses 流式模型。
- `test_build_chat_model_builds_chat_completions_transport_when_configured`：显式配置可选择 Chat Completions。
- `test_build_chat_model_rejects_unknown_transport`：拒绝未知模型传输方式。
- `test_normalize_model_config_rejects_untyped_dict_input`：拒绝未类型化的配置字典。
- `test_qa_records_text_from_responses_api_content_blocks`：从 Responses 内容块提取可见文本。
- `test_qa_records_terminal_stop_message_as_final_answer`：终止消息标记为最终回答。
- `test_qa_records_model_message_content_and_tool_calls_without_reasoning`：保留文本和工具调用，不输出隐藏推理。

执行入口改为直接消费 stream_completion(...) 异步生成器，不创建运行时对象。
