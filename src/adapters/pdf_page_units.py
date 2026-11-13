# Role: adapter
"""Extração de unidades lógicas por página de PDF e população de parágrafos."""

from __future__ import annotations

import re
from typing import List, Optional, Set, Tuple

import pymupdf

from src.domain.models import Chapter, EnhancementOptions, ParagraphItem
from src.policies.pdf_chapter_layers_explicit import LogicalUnit
from src.policies.pdf_heuristics import (
    ARTICLE_START_RE,
    CHAPTER_MARKER_RE,
    NUMBERED_ITEM_START_RE,
    STANDALONE_ARTICLE_RE,
    STANDALONE_CHAPTER_TITLES_RE,
    TOC_DOT_LEADER_RE,
    is_footnote_block,
    is_heading_candidate,
    is_running_header_or_footer,
    span_is_bold,
)
from src.policies.text_normalizer import (
    merge_two_texts,
    reflow_lines_in_block,
    should_merge_paragraphs,
    strip_control_chars,
    strip_page_brackets,
)


def _merge_drop_caps(units: List[LogicalUnit], body_font_size: float) -> List[LogicalUnit]:
    standalone_one = {"A", "O", "E", "À", "É", "I", "Y", "U"}
    complete_next = {
        "que", "qual", "quais", "quem", "quando", "onde", "como", "por", "para",
        "pelo", "pela", "pelos", "pelas", "em", "no", "na", "nos", "nas", "num",
        "numa", "de", "do", "da", "dos", "das", "se", "não", "já", "mais", "menos",
        "muito", "muita", "todo", "toda", "todos", "todas", "outro", "outra", "mesmo", "mesma", "um", "uma",
    }
    merged: List[LogicalUnit] = []
    idx_u = 0
    while idx_u < len(units):
        u_curr = units[idx_u]
        curr_txt = u_curr.text.strip()
        core_alpha = curr_txt.lstrip("“\"‘'([«")
        if (
            1 <= len(curr_txt) <= 3
            and len(core_alpha) == 1
            and core_alpha.isalpha()
            and u_curr.max_font_size >= body_font_size * 2.0
            and idx_u + 1 < len(units)
        ):
            u_next = units[idx_u + 1]
            if u_next.max_font_size <= body_font_size + 2.5 and abs(u_next.bbox[1] - u_curr.bbox[1]) <= u_curr.max_font_size * 0.9:
                next_txt = u_next.text.lstrip()
                first_word = re.split(r"[\s,.;:!?]+", next_txt)[0].lower() if next_txt else ""
                sep = " " if (next_txt and next_txt[0].isupper()) or (core_alpha.upper() in standalone_one and first_word in complete_next) else ""
                u_next.text = f"{curr_txt}{sep}{next_txt}"
                u_next.raw_text = f"{curr_txt}{u_next.raw_text}"
                u_next.bbox = (
                    min(u_curr.bbox[0], u_next.bbox[0]),
                    min(u_curr.bbox[1], u_next.bbox[1]),
                    max(u_curr.bbox[2], u_next.bbox[2]),
                    max(u_curr.bbox[3], u_next.bbox[3]),
                )
                merged.append(u_next)
                idx_u += 2
                continue
        merged.append(u_curr)
        idx_u += 1
    return merged


def _build_horizontal_lines(block: dict, body_font_size: float) -> List[dict]:
    merged_horiz: List[dict] = []
    for l in block.get("lines", []):
        l_bbox = tuple(l.get("bbox", (0.0, 0.0, 0.0, 0.0)))
        spans = l.get("spans", [])
        line_str = strip_control_chars("".join(s.get("text", "") for s in spans)).strip()

        if merged_horiz and line_str and merged_horiz[-1]["line_str"] and abs(l_bbox[1] - merged_horiz[-1]["bbox"][1]) <= 3.0:
            prev = merged_horiz[-1]
            if line_str == prev["line_str"] and abs(l_bbox[0] - prev["bbox"][0]) <= 5.0:
                continue
            prev["spans"].extend([{"text": " ", "size": prev["max_sz"], "font": "", "flags": 0}] + spans)
            prev["line_str"] = (prev["line_str"] + " " + line_str).strip()
            prev["bbox"] = (min(prev["bbox"][0], l_bbox[0]), min(prev["bbox"][1], l_bbox[1]), max(prev["bbox"][2], l_bbox[2]), max(prev["bbox"][3], l_bbox[3]))
            continue

        if merged_horiz and line_str and line_str == merged_horiz[-1]["line_str"] and abs(l_bbox[1] - merged_horiz[-1]["bbox"][1]) <= 6.0:
            continue

        non_empty = [(strip_control_chars(s.get("text", "")).strip(), float(s.get("size", body_font_size)), s) for s in spans if strip_control_chars(s.get("text", "")).strip()]
        max_sz = max((sz for _t, sz, _s in non_empty), default=0.0)
        if len(non_empty) >= 2:
            first_txt, first_sz, _ = non_empty[0]
            rest_max = max(sz for _t, sz, _s in non_empty[1:])
            if len(first_txt) <= 2 and first_sz >= body_font_size + 4.0 and sum(len(t) for t, _, _ in non_empty[1:]) >= 10 and rest_max <= body_font_size + 1.5:
                max_sz = rest_max
        merged_horiz.append({"bbox": l_bbox, "spans": list(spans), "line_str": line_str, "max_sz": max_sz or body_font_size})

    expanded: List[dict] = []
    inline_hdr_re = re.compile(r"^([A-ZÀ-Ú][^\n:]{2,70}?)\s*(?::\.?\s*[—–\-]+|:\s*I\b|:\s+—)\s*(.+)$")
    for hl in merged_horiz:
        m_in = inline_hdr_re.match(hl["line_str"])
        if m_in:
            hdr_part, body_part = m_in.group(1).strip(), m_in.group(2).strip()
            alpha_sp = [s for s in hl["spans"] if strip_control_chars(s.get("text", "")).strip()]
            first_sp = alpha_sp[0] if alpha_sp else {}
            styled = span_is_bold(first_sp) or bool(int(first_sp.get("flags", 0)) & 2) or "ital" in (first_sp.get("font") or "").lower()
            if styled and len(hdr_part) >= 3 and len(body_part) >= 5:
                x0, y0, x1, y1 = hl["bbox"]
                mid_y = y0 + (y1 - y0) * 0.45
                expanded.append({"bbox": (x0, y0, x1, mid_y), "spans": [{"text": hdr_part, "size": hl["max_sz"], "font": (first_sp.get("font") or "Bold") + ",Bold", "flags": int(first_sp.get("flags", 0)) | 16}], "line_str": hdr_part, "max_sz": hl["max_sz"]})
                expanded.append({"bbox": (x0, mid_y + 1.0, x1, y1), "spans": [{"text": body_part, "size": body_font_size, "font": "Regular", "flags": 0}], "line_str": body_part, "max_sz": body_font_size})
                continue
        cleaned_hdr = re.sub(r"\s*(?:,\s*saying\s*)?:\.?\s*[—–\-]+\s*$|\s+TO\s*~\s*$", "", hl["line_str"], flags=re.I).strip()
        if cleaned_hdr and cleaned_hdr != hl["line_str"]:
            hl = dict(hl)
            hl["line_str"] = cleaned_hdr
        expanded.append(hl)
    return expanded


def extract_page_logical_units(
    page: pymupdf.Page,
    page_num: int,
    body_font_size: float,
    opts: EnhancementOptions,
) -> Tuple[List[LogicalUnit], List[ParagraphItem]]:
    """Extrai blocos de uma página PDF em unidades lógicas ordenadas e notas de rodapé."""
    page_height = float(page.rect.height)
    units: List[LogicalUnit] = []
    footnotes: List[ParagraphItem] = []

    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0 or not block.get("lines"):
            continue
        lines_buf: List[str] = []
        bbox: Optional[Tuple[float, float, float, float]] = None
        max_sz, any_bold, all_bold = 0.0, False, True
        fonts: List[str] = []
        prev_y1: Optional[float] = None
        prev_h = 12.0

        def _flush() -> None:
            nonlocal lines_buf, bbox, max_sz, any_bold, all_bold, fonts, prev_y1
            if not lines_buf or bbox is None:
                lines_buf, bbox, max_sz, any_bold, all_bold, fonts, prev_y1 = [], None, 0.0, False, True, [], None
                return
            raw_u, u_bbox, u_sz, u_fonts, u_any_b, u_all_b = "\n".join(lines_buf).strip(), bbox, max_sz, list(fonts), any_bold, all_bold
            lines_buf, bbox, max_sz, any_bold, all_bold, fonts, prev_y1 = [], None, 0.0, False, True, [], None
            if not raw_u or (opts.remove_headers_footers and is_running_header_or_footer(u_bbox, raw_u, page_height, u_sz, body_font_size)):
                return
            if opts.footnote_mode in ("move_end", "remove") and is_footnote_block(u_bbox, raw_u, u_sz, body_font_size, page_height):
                if opts.footnote_mode == "move_end":
                    fn_txt = reflow_lines_in_block(raw_u, opts.normalize_chars, opts.reflow_sentences)
                    if fn_txt:
                        footnotes.append(ParagraphItem(text=f"[Nota pág. {page_num}] {fn_txt}", kind="footnote", page_number=page_num))
                return
            reflowed = reflow_lines_in_block(raw_u, opts.normalize_chars, opts.reflow_sentences)
            if reflowed:
                units.append(LogicalUnit(page_num, u_bbox, raw_u, reflowed, u_sz, u_any_b, u_all_b, u_fonts))

        for hl in _build_horizontal_lines(block, body_font_size):
            l_str = hl["line_str"]
            if not l_str:
                _flush()
                continue
            l_bbox, l_sz = hl["bbox"], hl["max_sz"]
            alpha_sp = [s for s in hl["spans"] if strip_control_chars(s.get("text", "")).strip()]
            l_any_b = any(span_is_bold(s) for s in alpha_sp)
            l_all_b = bool(alpha_sp) and all(span_is_bold(s) for s in alpha_sp)
            l_fonts = [s["font"] for s in alpha_sp if s.get("font")]

            if lines_buf:
                curr_joined = " ".join(lines_buf).strip()
                split = bool(
                    (prev_y1 is not None and (l_bbox[1] - prev_y1) > max(7.5, prev_h * 0.65) and not (max_sz >= body_font_size + 5.0 and abs(l_sz - max_sz) <= 2.5))
                    or CHAPTER_MARKER_RE.match(l_str) or STANDALONE_CHAPTER_TITLES_RE.match(l_str)
                    or TOC_DOT_LEADER_RE.search(lines_buf[-1]) or TOC_DOT_LEADER_RE.search(l_str)
                    or ((CHAPTER_MARKER_RE.match(curr_joined) or STANDALONE_CHAPTER_TITLES_RE.match(curr_joined)) and (ARTICLE_START_RE.match(l_str) or not (l_str.isupper() or l_all_b or l_sz >= body_font_size + 1.5)))
                    or ARTICLE_START_RE.match(l_str) or STANDALONE_ARTICLE_RE.match(curr_joined)
                    or abs(l_sz - max_sz) >= 1.5
                    or (NUMBERED_ITEM_START_RE.match(l_str) and (l_all_b or all_bold != l_all_b or lines_buf[-1].endswith((".", ":", ";", "!", "?"))))
                    or ((all_bold or any_bold) and not l_any_b and len(curr_joined) <= 130 and (not curr_joined.endswith(".") or curr_joined.isupper()))
                    or (l_all_b and (all_bold != l_all_b or any_bold != l_any_b) and (NUMBERED_ITEM_START_RE.match(l_str) or l_str.isupper()))
                )
                if split:
                    _flush()
            lines_buf.append(l_str)
            bbox = l_bbox if bbox is None else (min(bbox[0], l_bbox[0]), min(bbox[1], l_bbox[1]), max(bbox[2], l_bbox[2]), max(bbox[3], l_bbox[3]))
            all_bold = l_all_b if len(lines_buf) == 1 else (all_bold and l_all_b)
            max_sz = max(max_sz, l_sz)
            any_bold = any_bold or l_any_b
            fonts.extend(l_fonts)
            prev_y1 = l_bbox[3]
            prev_h = max(8.0, l_bbox[3] - l_bbox[1])
        _flush()

    units.sort(key=lambda u: (round(u.bbox[1], 1), round(u.bbox[0], 1)))
    return _merge_drop_caps(units, body_font_size), footnotes


def populate_chapter_items_from_units(
    chapter: Chapter,
    units_slice: List[LogicalUnit],
    consumed_indices: Set[int],
    slice_offset: int,
    footnotes: List[ParagraphItem],
    body_font_size: float,
    opts: EnhancementOptions,
) -> None:
    """Converte fatia de unidades lógicas em itens do capítulo com união entre blocos/páginas."""
    for rel_idx, u in enumerate(units_slice):
        if (slice_offset + rel_idx) in consumed_indices or not u.text:
            continue
        heading_kind = is_heading_candidate(u.text, u.max_font_size, u.is_bold, u.fonts, body_font_size, chapter.title)
        if heading_kind == "skip":
            continue
        if heading_kind == "h2":
            chapter.items.append(ParagraphItem(text=strip_page_brackets(u.text), kind="h2", page_number=u.page_num))
            continue
        if re.match(r"^(\([0-9a-zA-Z]+\)|[0-9]+\.)\s+", u.text):
            for sub in re.split(r"(?=\s+\([0-9a-zA-Z]+\)\s+)", u.text):
                if sub.strip():
                    chapter.items.append(ParagraphItem(text=sub.strip(), kind="list_item", page_number=u.page_num))
            continue
        if chapter.items and chapter.items[-1].kind == "h2" and len(chapter.items[-1].text.split()) == 1 and chapter.items[-1].text.lower().rstrip(":") in ("perfumes", "perfume", "incense", "incenso"):
            lbl = chapter.items[-1].text.rstrip(":")
            chapter.items[-1].kind = "p"
            chapter.items[-1].text = f"{lbl}: {u.text}"
            continue
        if opts.reflow_sentences and chapter.items and chapter.items[-1].kind in ("p", "list_item") and should_merge_paragraphs(chapter.items[-1].text, u.text):
            chapter.items[-1].text = merge_two_texts(chapter.items[-1].text, u.text)
        else:
            chapter.items.append(ParagraphItem(text=u.text, kind="p", page_number=u.page_num))

    if footnotes:
        chapter.items.append(ParagraphItem(text="Notas do Capítulo", kind="h2", page_number=chapter.end_page))
        chapter.items.extend(footnotes)
