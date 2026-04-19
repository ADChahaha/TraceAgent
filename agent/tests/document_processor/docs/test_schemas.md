# `test_schemas.py`

一句话：这个文件用来钉住 `document_processor.schemas` 的数据结构，不让后面改着改着把返回格式改坏。

## 测什么

- `BoundingBox` 的字段顺序和坐标值
- `ContentBlock` 的默认值
- `ContentBlock.meta_info` 不会在实例之间串数据
- `ProcessResult` 的核心字段和默认值
- `ProcessResult` 的列表/字典默认容器不共享
- `ProcessResult` 能被 `asdict()` 正常展开

## 每个函数在干什么

`test_bounding_box_keeps_coordinate_field_order`

- 检查 `BoundingBox` 是 dataclass。
- 检查字段顺序固定为 `x0/y0/x1/y1`。
- 检查传进去的坐标值会原样保留。

`test_content_block_uses_route_compatible_defaults`

- 检查 `ContentBlock(text="hello")` 在最小输入下能正常构造。
- 检查 `page_no`、`bbox`、`kind`、`meta_info` 的默认值符合 route 现在的读取预期。

`test_content_block_meta_info_is_not_shared_between_instances`

- 先创建两个 `ContentBlock`。
- 改第一个对象的 `meta_info`。
- 确认第二个对象不受影响，避免共享默认字典。

`test_process_result_exposes_normalized_output_fields_with_safe_defaults`

- 检查 `ProcessResult` 是 dataclass。
- 检查它包含 `file_type`、`filename`、`md_list`、`markdown`、`blocks`、`meta_info`、`warnings` 这些核心字段。
- 检查这些字段在最小构造下都有安全默认值。

`test_process_result_default_containers_are_not_shared_between_instances`

- 先创建两个 `ProcessResult`。
- 修改第一个对象里的列表和字典字段。
- 确认第二个对象还是空的，避免不同处理结果之间串状态。

`test_process_result_serializes_nested_blocks_as_plain_dataclass_data`

- 构造带 `BoundingBox` 和 `ContentBlock` 的完整 `ProcessResult`。
- 用 `asdict()` 展开。
- 检查展开后的结果是不是普通字典和列表，并且字段内容完全符合预期。

## 为什么有它

`document_processor` 后面会被 route 和抽取流程一起消费。这个测试文件先把最基础的 schema 契约固定住，后面补 `processor.py`、`types.py` 时不容易把输出结构带偏。

## 怎么跑

```bash
source <conda-env>/etc/profile.d/conda.sh
conda activate agent-gate
python -m pytest tests/document_processor/test_schemas.py -q
```
