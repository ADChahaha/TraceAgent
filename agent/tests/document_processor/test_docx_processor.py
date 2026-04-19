from io import BytesIO
import pytest
from docx import Document


class NamedBytesIO(BytesIO):
    def __init__(self, data: bytes, filename: str | None = None) -> None:
        super().__init__(data)
        self.filename = filename


def build_docx_file(*paragraphs: str, heading: str | None = None) -> NamedBytesIO:
    buffer = BytesIO()
    document = Document()
    if heading is not None:
        document.add_heading(heading, level=1)
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(buffer)
    return NamedBytesIO(buffer.getvalue(), filename="sample.docx")


def test_docx_processor_uses_python_docx_to_generate_markdown_and_blocks():
    from document_processor.impl.docx.processor import DocxProcessor

    result = DocxProcessor().process(
        build_docx_file("第一段内容", "第二段内容", heading="测试标题")
    )

    assert result.file_type == "docx"
    assert result.filename == "sample.docx"
    assert result.warnings == []
    assert "测试标题" in result.markdown
    assert "第一段内容" in result.markdown
    assert "第二段内容" in result.markdown
    assert result.md_list == [result.markdown]
    assert [block.text for block in result.blocks] == ["测试标题", "第一段内容", "第二段内容"]
    assert [block.kind for block in result.blocks] == ["section_header", "text", "text"]


def test_docx_processor_uses_python_docx_instead_of_docling():
    from document_processor.impl.docx import processor as processor_module
    from document_processor.impl.docx.processor import DocxProcessor

    assert not hasattr(processor_module, "DocumentConverter")

    result = DocxProcessor().process(build_docx_file("正文内容"))

    assert "正文内容" in result.markdown


def test_docx_processor_uses_default_filename_when_input_has_no_name():
    from document_processor.impl.docx.processor import DocxProcessor

    result = DocxProcessor().process(NamedBytesIO(build_docx_file("内容").getvalue()))

    assert result.filename == "document.docx"
