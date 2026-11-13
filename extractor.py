# Role: service
"""Fachada pública compatível de extração de livros (PDF, EPUB, TXT, MD)."""

from __future__ import annotations

from src.adapters.epub_parser import extract_epub_book
from src.adapters.pdf_extractor import extract_pdf_book
from src.adapters.text_md_parser import extract_text_or_markdown_book
from src.domain.models import (
    BookStructure,
    Chapter,
    EnhancementOptions,
    ParagraphItem,
)
from src.policies.text_normalizer import (
    normalize_typography,
    reflow_lines_in_block,
    strip_control_chars,
)
from src.services.book_io_dispatch import extract_book_any as extract_book

__all__ = [
    "EnhancementOptions",
    "ParagraphItem",
    "Chapter",
    "BookStructure",
    "extract_book",
    "extract_pdf_book",
    "extract_epub_book",
    "extract_text_or_markdown_book",
    "normalize_typography",
    "reflow_lines_in_block",
    "strip_control_chars",
]
