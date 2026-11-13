# Role: adapter
"""Adaptador de extração para arquivos TXT e Markdown com filtro de capítulos."""

from __future__ import annotations

import os
import re
from typing import List, Optional

from src.domain.models import BookStructure, Chapter, EnhancementOptions, ParagraphItem
from src.policies.path_policy import validate_page_bounds
from src.policies.pdf_heuristics import CHAPTER_MARKER_RE, STANDALONE_CHAPTER_TITLES_RE
from src.policies.text_normalizer import normalize_typography, reflow_lines_in_block

_MD_H1_RE = re.compile(r"^#\s+(.+)$")
_MD_SUBHEADING_RE = re.compile(r"^#{2,6}\s+(.+)$")
_MD_LIST_RE = re.compile(r"^(?:[-*+]\s+|\d{1,3}\.\s+)(.+)$")


def extract_text_or_markdown_book(
    file_path: str,
    options: Optional[EnhancementOptions] = None,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
) -> BookStructure:
    """Extrai capítulos e parágrafos de TXT/Markdown preservando '#' internos nos títulos."""
    validate_page_bounds(start_page, end_page)
    opts = options or EnhancementOptions()
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    if opts.normalize_chars:
        content = normalize_typography(content, enabled=True)

    base_title = os.path.splitext(os.path.basename(file_path))[0].replace("_", " ").title()
    chapters: List[Chapter] = []
    current_chapter = Chapter(index=1, title="Início", start_page=1, end_page=1)
    detected_any_chapter = False

    for block in re.split(r"\n\s*\n", content):
        b = block.strip()
        if not b:
            continue

        m_h1 = _MD_H1_RE.match(b)
        if opts.organize_toc and m_h1:
            detected_any_chapter = True
            if current_chapter.items:
                chapters.append(current_chapter)
            current_chapter = Chapter(
                index=len(chapters) + 1,
                title=m_h1.group(1).strip(),
                start_page=1,
                end_page=1,
            )
            continue

        is_single_line = "\n" not in b and len(b) <= 90
        if (
            opts.organize_toc
            and is_single_line
            and (
                CHAPTER_MARKER_RE.match(b)
                or STANDALONE_CHAPTER_TITLES_RE.match(b)
                or (b.isupper() and 4 <= len(b) <= 65 and not b.endswith("."))
            )
        ):
            detected_any_chapter = True
            if current_chapter.items:
                chapters.append(current_chapter)
            current_chapter = Chapter(
                index=len(chapters) + 1,
                title=b.strip(),
                start_page=1,
                end_page=1,
            )
            continue

        m_sub = _MD_SUBHEADING_RE.match(b)
        if m_sub:
            current_chapter.items.append(
                ParagraphItem(text=m_sub.group(1).strip(), kind="h2", page_number=1)
            )
            continue

        if _MD_LIST_RE.match(b):
            for ln in b.splitlines():
                ln_s = ln.strip()
                m_li = _MD_LIST_RE.match(ln_s)
                item_txt = reflow_lines_in_block(
                    m_li.group(1) if m_li else ln_s,
                    do_normalize=opts.normalize_chars,
                    do_reflow=opts.reflow_sentences,
                )
                if item_txt:
                    current_chapter.items.append(ParagraphItem(text=item_txt, kind="list_item", page_number=1))
            continue

        cleaned = reflow_lines_in_block(
            b, do_normalize=opts.normalize_chars, do_reflow=opts.reflow_sentences
        )
        if cleaned:
            current_chapter.items.append(ParagraphItem(text=cleaned, kind="p", page_number=1))

    if current_chapter.items:
        chapters.append(current_chapter)

    if (
        opts.organize_toc
        and not detected_any_chapter
        and len(chapters) == 1
        and len(chapters[0].items) > 60
    ):
        all_items = chapters[0].items
        chapters = []
        chunk_size = 40
        for idx, start_i in enumerate(range(0, len(all_items), chunk_size), start=1):
            sub_items = all_items[start_i: start_i + chunk_size]
            first_words = " ".join(sub_items[0].text.split()[:6]).rstrip(".,;:") + "..."
            chapters.append(
                Chapter(
                    index=idx,
                    title=f"Capítulo {idx} ({first_words})",
                    start_page=idx,
                    end_page=idx,
                    items=sub_items,
                )
            )
        method = "auto_segmented_txt"
    else:
        method = "heuristic_txt" if detected_any_chapter else "single_section"

    if start_page is not None or end_page is not None:
        s_idx = (start_page or 1) - 1
        e_idx = end_page if end_page is not None else len(chapters)
        chapters = chapters[s_idx:e_idx]
        for new_idx, ch in enumerate(chapters, start=1):
            ch.index = new_idx

    return BookStructure(
        title=base_title,
        author="Autor Desconhecido",
        source_path=file_path,
        chapters=chapters,
        toc_discovery_method=method,
    )
