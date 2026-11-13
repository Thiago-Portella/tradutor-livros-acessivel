# Role: service
"""Despachante único para extração e exportação nos formatos suportados."""

from __future__ import annotations

import os
from typing import Optional

from src.adapters.epub_exporter import build_epub
from src.adapters.epub_parser import extract_epub_book
from src.adapters.html_exporter import build_html
from src.adapters.md_txt_exporter import build_markdown, build_txt
from src.adapters.pdf_exporter import build_pdf
from src.adapters.pdf_extractor import extract_pdf_book
from src.adapters.text_md_parser import extract_text_or_markdown_book
from src.domain.models import BookStructure, EnhancementOptions


def extract_book_any(
    file_path: str,
    options: Optional[EnhancementOptions] = None,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
) -> BookStructure:
    opts = options or EnhancementOptions()
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return extract_pdf_book(file_path, options=opts, start_page=start_page, end_page=end_page)
    if ext == ".epub":
        return extract_epub_book(file_path, options=opts, start_page=start_page, end_page=end_page)
    return extract_text_or_markdown_book(file_path, options=opts, start_page=start_page, end_page=end_page)


def export_book_any(
    book: BookStructure,
    output_path: str,
    fmt: str = "epub",
    target_lang: str = "pt",
    source_lang: str = "en",
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    fmt_clean = fmt.lower().lstrip(".")
    if fmt_clean == "markdown":
        fmt_clean = "md"
    builders = {
        "epub": build_epub,
        "pdf": build_pdf,
        "html": build_html,
        "md": build_markdown,
        "txt": build_txt,
    }
    builder = builders.get(fmt_clean)
    if not builder:
        raise ValueError(f"Formato de saída não suportado: {fmt}")
    return builder(
        book,
        output_path,
        target_lang=target_lang,
        source_lang=source_lang,
        bilingual=bilingual,
        include_back_to_toc=include_back_to_toc,
    )
