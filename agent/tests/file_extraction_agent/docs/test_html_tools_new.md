# test_html_tools_new.py

这份测试覆盖新抽取工具层。工具围绕虚拟文件树工作，并在每次调用时写入流式事件；字段写入使用 `path + sentences/items/rows` evidence selector。

实现链路：

```text
documents + task_spec
  -> build_graph_input / build_graph_state
  -> tree/read/anchors/query_table 浏览材料
  -> write_field 写入可覆盖字段定案
  -> submit_result 做 schema 与 evidence 校验
  -> state.events 记录真实工具事件
```

## 测试函数

- `test_build_tools_exposes_virtual_tree_tools_only`：确认模型只看到 `tree/read/anchors/query_table/write_field/submit_result`，不再暴露 soft plan、旧 block 读取和 record note 工具。
- `test_tree_read_anchors_and_query_record_reasoned_events`：确认浏览、读取、句子编号和表格查询都会记录带 `reason` 的 started/completed 事件。
- `test_write_field_overwrites_result_buffer_and_validates_selectors`：确认同一字段可覆盖写入，成功写入会附带从 evidence selector 反查出来的 `evidence_texts`，错误 selector 会返回失败且不污染字段结果。
- `test_submit_result_validates_required_fields_and_returns_new_field_shape`：确认 `submit_result` 校验必填字段、类型和 evidence，并返回字段对象数组的新结果形态。
