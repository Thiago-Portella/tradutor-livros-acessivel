# Role: adapter
"""Adaptador de extração completa de livros PDF com suporte a TOC embutido sub-página."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import pymupdf

from src.adapters.pdf_page_units import (
    extract_page_logical_units,
    populate_chapter_items_from_units,
)
from src.domain.models import BookStructure, Chapter, EnhancementOptions, ParagraphItem
from src.policies.path_policy import validate_page_bounds
from src.policies.pdf_chapter_discovery import (
    detect_printed_toc_pages,
    discover_chapters_from_units,
)
from src.policies.pdf_chapter_layers_explicit import LogicalUnit
from src.policies.pdf_metadata_policy import (
    estimate_body_font_size,
    guess_pdf_book_metadata,
)
from src.policies.text_normalizer import normalize_typography, strip_page_brackets


def _is_toc_title(title: str) -> bool:
    return strip_page_brackets(title).lower() in (
        "contents", "table of contents", "sumário", "sumario",
        "índice", "indice", "i n d i c e", "conteúdo",
    )


def _locate_unit_for_toc_entry(
    all_units: List[LogicalUnit],
    entry_title: str,
    target_page: int,
    min_unit_idx: int,
) -> int:
    """Encontra o índice exato da unidade inicial de uma entrada do TOC, inclusive na mesma página."""
    norm_target = re.sub(r"[^a-z0-9]+", " ", entry_title.lower()).strip()
    page_indices = [
        idx for idx in range(min_unit_idx, len(all_units)) if all_units[idx].page_num == target_page
    ]
    if page_indices and norm_target:
        for idx in page_indices:
            u_norm = re.sub(r"[^a-z0-9]+", " ", all_units[idx].text.lower()).strip()
            if u_norm == norm_target or norm_target in u_norm or (len(u_norm) >= 4 and u_norm in norm_target):
                return idx
        return page_indices[0]
    for idx in range(min_unit_idx, len(all_units)):
        if all_units[idx].page_num >= target_page:
            return idx
    return len(all_units)


def _extract_from_embedded_toc(
    raw_toc: list,
    pages_units: Dict[int, List[LogicalUnit]],
    pages_footnotes: Dict[int, List[ParagraphItem]],
    p_start: int,
    p_end: int,
    body_font_size: float,
    opts: EnhancementOptions,
) -> List[Chapter]:
    lvl1 = [(title.strip(), max(1, page)) for lvl, title, page in raw_toc if lvl == 1]
    if len(lvl1) < 2:
        lvl1 = [(title.strip(), max(1, page)) for lvl, title, page in raw_toc]

    filtered_toc = [
        (normalize_typography(t, opts.normalize_chars), pg)
        for t, pg in lvl1
        if p_start <= pg <= p_end or (pg < p_start and len(lvl1) == 1)
    ]
    if not filtered_toc:
        filtered_toc = [(normalize_typography(t, opts.normalize_chars), max(p_start, min(p_end, pg))) for t, pg in lvl1]

    all_units = [u for p in range(p_start, p_end + 1) for u in pages_units.get(p, [])]
    if not all_units or not filtered_toc:
        return []

    starts: List[Tuple[str, int]] = []
    cursor = 0
    for ch_title, ch_page in filtered_toc:
        if ch_page < p_start:
            continue
        start_idx = _locate_unit_for_toc_entry(all_units, ch_title, ch_page, cursor)
        if start_idx < len(all_units):
            starts.append((ch_title, start_idx))
            cursor = start_idx + 1

    if not starts:
        starts.append((filtered_toc[0][0], 0))
    elif starts[0][1] > 0:
        pre_units = all_units[:starts[0][1]]
        pre_words = sum(len(u.text.split()) for u in pre_units)
        if not (all(u.page_num == p_start for u in pre_units) and pre_words < 35):
            starts.insert(0, ("Informações Iniciais", 0))

    chapters: List[Chapter] = []
    page_last_chapter: Dict[int, Chapter] = {}
    for idx_s, (ch_title, start_u) in enumerate(starts):
        end_u = starts[idx_s + 1][1] if idx_s + 1 < len(starts) else len(all_units)
        if _is_toc_title(ch_title) and len(starts) > 1:
            continue
        u_slice = all_units[start_u:end_u]
        if not u_slice:
            continue
        c_start, c_end = u_slice[0].page_num, u_slice[-1].page_num
        ch = Chapter(index=len(chapters) + 1, title=ch_title, start_page=c_start, end_page=c_end)
        populate_chapter_items_from_units(ch, u_slice, set(), start_u, [], body_font_size, opts)
        if ch.items:
            chapters.append(ch)
            for p in range(c_start, c_end + 1):
                page_last_chapter[p] = ch

    for p in range(p_start, p_end + 1):
        fns = pages_footnotes.get(p, [])
        if fns and p in page_last_chapter:
            target = page_last_chapter[p]
            if not any(it.kind == "h2" and it.text == "Notas do Capítulo" for it in target.items):
                target.items.append(ParagraphItem(text="Notas do Capítulo", kind="h2", page_number=target.end_page))
            target.items.extend(fns)
    return chapters


def extract_pdf_book(
    pdf_path: str,
    options: Optional[EnhancementOptions] = None,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
) -> BookStructure:
    """Extrai um livro PDF preservando estrutura, sumário e notas conforme opções."""
    validate_page_bounds(start_page, end_page)
    opts = options or EnhancementOptions()

    with pymupdf.open(pdf_path) as doc:
        total_pages = len(doc)
        book_title, book_author = guess_pdf_book_metadata(doc, pdf_path)
        p_start = max(1, start_page or 1)
        p_end = min(total_pages, end_page or total_pages)
        body_font_size = estimate_body_font_size(doc)

        pages_units: Dict[int, List[LogicalUnit]] = {}
        pages_footnotes: Dict[int, List[ParagraphItem]] = {}
        for page_num in range(p_start, p_end + 1):
            u_list, fn_list = extract_page_logical_units(doc[page_num - 1], page_num, body_font_size, opts)
            pages_units[page_num] = u_list
            pages_footnotes[page_num] = fn_list

        chapters: List[Chapter] = []
        discovery_method = "embedded_toc"

        if not opts.organize_toc:
            all_units = [u for p in range(p_start, p_end + 1) for u in pages_units.get(p, [])]
            all_fns = [fn for p in range(p_start, p_end + 1) for fn in pages_footnotes.get(p, [])]
            ch = Chapter(index=1, title=book_title, start_page=p_start, end_page=p_end)
            populate_chapter_items_from_units(ch, all_units, set(), 0, all_fns, body_font_size, opts)
            if ch.items:
                chapters.append(ch)
            return BookStructure(book_title, book_author, pdf_path, chapters, "single_section")

        raw_toc = [] if opts.force_heuristic_toc else doc.get_toc()
        if raw_toc:
            chapters = _extract_from_embedded_toc(
                raw_toc, pages_units, pages_footnotes, p_start, p_end, body_font_size, opts
            )
        else:
            toc_pages, printed_entries = detect_printed_toc_pages(pages_units, total_pages)
            body_units = [u for p in range(p_start, p_end + 1) if p not in toc_pages for u in pages_units.get(p, [])]
            if not body_units:
                body_units = [u for p in range(p_start, p_end + 1) for u in pages_units.get(p, [])]
            spans, consumed_indices, discovery_method = discover_chapters_from_units(
                body_units, body_font_size, printed_entries, toc_pages, p_start, p_end, book_title=book_title
            )
            page_last_chapter: Dict[int, Chapter] = {}
            for ch_title, start_u, end_u in spans:
                if _is_toc_title(ch_title) and len(spans) > 1:
                    continue
                u_slice = body_units[start_u:end_u]
                if not u_slice:
                    continue
                c_start, c_end = u_slice[0].page_num, u_slice[-1].page_num
                ch = Chapter(index=len(chapters) + 1, title=normalize_typography(ch_title, opts.normalize_chars), start_page=c_start, end_page=c_end)
                populate_chapter_items_from_units(ch, u_slice, consumed_indices, start_u, [], body_font_size, opts)
                if ch.items:
                    chapters.append(ch)
                    for p in range(c_start, c_end + 1):
                        page_last_chapter[p] = ch
            for p in range(p_start, p_end + 1):
                fns = pages_footnotes.get(p, [])
                if fns and p in page_last_chapter:
                    target = page_last_chapter[p]
                    if not any(it.kind == "h2" and it.text == "Notas do Capítulo" for it in target.items):
                        target.items.append(ParagraphItem(text="Notas do Capítulo", kind="h2", page_number=target.end_page))
                    target.items.extend(fns)

    return BookStructure(book_title, book_author, pdf_path, chapters, discovery_method)
