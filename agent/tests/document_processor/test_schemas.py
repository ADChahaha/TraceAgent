from dataclasses import asdict, fields, is_dataclass

from document_processor.schemas import BoundingBox, ContentBlock, ProcessResult


def test_bounding_box_keeps_coordinate_field_order():
    bbox = BoundingBox(x0=1.0, y0=2.0, x1=3.5, y1=4.5)

    assert is_dataclass(BoundingBox)
    assert [field.name for field in fields(BoundingBox)] == ["x0", "y0", "x1", "y1"]
    assert (bbox.x0, bbox.y0, bbox.x1, bbox.y1) == (1.0, 2.0, 3.5, 4.5)


def test_content_block_uses_route_compatible_defaults():
    block = ContentBlock(text="hello")

    assert is_dataclass(ContentBlock)
    assert block.text == "hello"
    assert block.page_no is None
    assert block.bbox is None
    assert block.kind == "text"
    assert block.meta_info == {}


def test_content_block_meta_info_is_not_shared_between_instances():
    first = ContentBlock(text="first")
    second = ContentBlock(text="second")

    first.meta_info["page_label"] = "1"

    assert second.meta_info == {}


def test_process_result_exposes_normalized_output_fields_with_safe_defaults():
    result = ProcessResult(file_type="pdf", filename="sample.pdf")

    assert is_dataclass(ProcessResult)
    assert result.file_type == "pdf"
    assert result.filename == "sample.pdf"
    assert result.md_list == []
    assert result.markdown == ""
    assert result.blocks == []
    assert result.meta_info == {}
    assert result.warnings == []


def test_process_result_default_containers_are_not_shared_between_instances():
    first = ProcessResult(file_type="pdf")
    second = ProcessResult(file_type="docx")

    first.md_list.append("# Title")
    first.blocks.append(ContentBlock(text="block"))
    first.meta_info["pages"] = 1
    first.warnings.append("ocr warning")

    assert second.md_list == []
    assert second.blocks == []
    assert second.meta_info == {}
    assert second.warnings == []


def test_process_result_serializes_nested_blocks_as_plain_dataclass_data():
    bbox = BoundingBox(x0=0.0, y0=1.0, x1=2.0, y1=3.0)
    block = ContentBlock(
        text="Body",
        page_no=2,
        bbox=bbox,
        kind="paragraph",
        meta_info={"section": "intro"},
    )
    result = ProcessResult(
        file_type="pdf",
        filename="sample.pdf",
        md_list=["# Title"],
        markdown="# Title",
        blocks=[block],
        meta_info={"pages": 3},
        warnings=["ocr fallback"],
    )

    assert asdict(result) == {
        "file_type": "pdf",
        "filename": "sample.pdf",
        "md_list": ["# Title"],
        "markdown": "# Title",
        "blocks": [
            {
                "text": "Body",
                "page_no": 2,
                "bbox": {"x0": 0.0, "y0": 1.0, "x1": 2.0, "y1": 3.0},
                "kind": "paragraph",
                "meta_info": {"section": "intro"},
            }
        ],
        "meta_info": {"pages": 3},
        "warnings": ["ocr fallback"],
    }
