# Role: service
"""Fachada pública compatível de exportação nos formatos EPUB, PDF, HTML, MD e TXT."""

from __future__ import annotations

from src.adapters.epub_exporter import build_epub
from src.adapters.html_exporter import build_html
from src.adapters.md_txt_exporter import build_markdown, build_txt
from src.adapters.pdf_exporter import build_pdf
from src.domain.models import SUPPORTED_FORMATS
from src.services.book_io_dispatch import export_book_any as export_book

__all__ = [
    "SUPPORTED_FORMATS",
    "build_epub",
    "build_pdf",
    "build_html",
    "build_markdown",
    "build_txt",
    "export_book",
]
