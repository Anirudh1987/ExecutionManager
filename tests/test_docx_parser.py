"""Tests for DOCX text extraction."""

import io
from docx import Document

from src.engine.docx_parser import extract_text_from_docx


class TestDocxParser:
    def _make_docx(self, paragraphs: list[str], table_data: list[list[str]] | None = None) -> bytes:
        doc = Document()
        for text in paragraphs:
            doc.add_paragraph(text)
        if table_data:
            table = doc.add_table(rows=len(table_data), cols=len(table_data[0]))
            for i, row in enumerate(table_data):
                for j, cell in enumerate(row):
                    table.rows[i].cells[j].text = cell
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    def test_basic_extraction(self):
        docx_bytes = self._make_docx(["First paragraph.", "Second paragraph."])
        text, pages = extract_text_from_docx(docx_bytes)
        assert "First paragraph" in text
        assert "Second paragraph" in text
        assert pages >= 1

    def test_empty_paragraphs_skipped(self):
        docx_bytes = self._make_docx(["Content", "", "  ", "More content"])
        text, _ = extract_text_from_docx(docx_bytes)
        assert "Content" in text
        assert "More content" in text

    def test_table_extraction(self):
        docx_bytes = self._make_docx(
            ["Introduction"],
            table_data=[["Header1", "Header2"], ["Value1", "Value2"]],
        )
        text, _ = extract_text_from_docx(docx_bytes)
        assert "Header1" in text
        assert "Value1" in text

    def test_page_estimation(self):
        # 10k characters should be ~3 pages
        long_text = "This is a long paragraph. " * 200
        docx_bytes = self._make_docx([long_text])
        _, pages = extract_text_from_docx(docx_bytes)
        assert pages >= 1
