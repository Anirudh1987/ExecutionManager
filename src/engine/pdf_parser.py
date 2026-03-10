"""PDF text extraction using PyMuPDF."""

from __future__ import annotations

import fitz  # PyMuPDF


def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, int]:
    """Extract text and page count from a PDF file.

    Returns:
        (raw_text, page_count)
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        if text.strip():
            pages.append(text)

    page_count = len(doc)
    doc.close()

    raw_text = "\n\n".join(pages)
    return raw_text, page_count
