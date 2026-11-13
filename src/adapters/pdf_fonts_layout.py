# Role: adapter
"""Seleção de fontes Unicode, quebra segura de URLs e layout de páginas A4 para PDF."""

from __future__ import annotations

import os
from typing import List, Tuple

import pymupdf

from src.domain.models import BookStructure, Chapter
from src.policies.i18n_labels import BookLabels

LineCmd = Tuple[float, str, str, float, Tuple[float, float, float], bool]


def clean_pdf_text(text: str) -> str:
    if not text:
        return ""
    for ch_invis in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060", "\xad"):
        text = text.replace(ch_invis, "")
    return " ".join(text.replace("\u00a0", " ").replace("\u202f", " ").split())


def escape_pdf_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _sample_book_text(book: BookStructure, labels: BookLabels) -> str:
    parts = [book.title, book.original_title, book.author, labels.toc_title]
    for ch in book.chapters[:10]:
        parts.append(ch.translated_title or ch.title)
        for it in ch.items[:25]:
            parts.append(it.translated_text or it.text)
    return " ".join(p for p in parts if p)


def load_pdf_fonts(book: BookStructure, labels: BookLabels) -> Tuple[pymupdf.Font, pymupdf.Font, pymupdf.Font]:
    """Seleciona fontes compatíveis com ElevenReader e faz fallback Unicode para scripts não-latinos."""
    sample = _sample_book_text(book, labels)
    needs_unicode = any(ord(ch) > 0x024F and ch not in "—–…“”‘’•↑°ºª€£¥©®™" for ch in sample)
    if needs_unicode:
        has_cjk = any(0x2E80 <= ord(c) <= 0xD7AF or 0x0600 <= ord(c) <= 0x06FF or 0x0900 <= ord(c) <= 0x0D7F for c in sample)
        if has_cjk:
            for path in (
                r"C:\Windows\Fonts\malgun.ttf",
                r"C:\Windows\Fonts\msyh.ttc",
                r"C:\Windows\Fonts\YuGothR.ttc",
                r"C:\Windows\Fonts\nirmala.ttf",
                r"C:\Windows\Fonts\arial.ttf",
            ):
                if os.path.exists(path):
                    f = pymupdf.Font(fontfile=path)
                    return f, f, f
            return pymupdf.Font("cjk"), pymupdf.Font("cjk"), pymupdf.Font("cjk")

        win_reg = r"C:\Windows\Fonts\arial.ttf"
        win_bold = r"C:\Windows\Fonts\arialbd.ttf"
        win_ital = r"C:\Windows\Fonts\ariali.ttf"
        if os.path.exists(win_reg):
            return (
                pymupdf.Font(fontfile=win_reg),
                pymupdf.Font(fontfile=win_bold if os.path.exists(win_bold) else win_reg),
                pymupdf.Font(fontfile=win_ital if os.path.exists(win_ital) else win_reg),
            )
    return pymupdf.Font("tiro"), pymupdf.Font("tibo"), pymupdf.Font("tiit")


def wrap_pdf_text(text: str, font: pymupdf.Font, fsize: float, width_limit: float) -> List[str]:
    """Quebra texto em linhas respeitando a largura útil, inclusive para URLs gigantes sem espaços."""
    words = clean_pdf_text(text).split()
    if not words:
        return []

    def _split_oversized(word: str) -> List[str]:
        parts: List[str] = []
        buf = ""
        for ch in word:
            cand = buf + ch
            if buf and font.text_length(cand, fontsize=fsize) > width_limit:
                parts.append(buf)
                buf = ch
            else:
                buf = cand
        if buf:
            parts.append(buf)
        return parts

    lines: List[str] = []
    curr = ""
    for w in words:
        cand = f"{curr} {w}" if curr else w
        if font.text_length(cand, fontsize=fsize) <= width_limit:
            curr = cand
            continue
        if curr:
            lines.append(curr)
            curr = ""
        if font.text_length(w, fontsize=fsize) <= width_limit:
            curr = w
        else:
            pieces = _split_oversized(w)
            lines.extend(pieces[:-1])
            curr = pieces[-1]
    if curr:
        lines.append(curr)
    return lines


def prepare_chapter_heading(
    idx: int,
    raw_title: str,
    chapter_word: str,
    font_bold: pymupdf.Font,
    ch_title_fsize: float,
    max_width: float,
) -> Tuple[str, List[str]]:
    """Garante bloco de abertura com >= 2 linhas para detecção confiável em leitores."""
    clean_t = clean_pdf_text(raw_title)
    if len(clean_t.split()) <= 1 or len(clean_t) < 15:
        display_title = f"{chapter_word} {idx} — {clean_t}" if clean_t else f"{chapter_word} {idx}"
    else:
        display_title = clean_t

    wrapped = wrap_pdf_text(display_title, font_bold, ch_title_fsize, max_width)
    if len(wrapped) == 1:
        line_str = wrapped[0]
        if " — " in line_str:
            p1, p2 = line_str.split(" — ", 1)
            if p1.strip() and p2.strip():
                return display_title, [f"{p1.strip()} —", p2.strip()]
        w_list = line_str.split()
        if len(w_list) >= 2:
            total_chars = sum(len(w) for w in w_list)
            best_split, best_diff, acc = 1, total_chars, 0
            for split_i in range(1, len(w_list)):
                acc += len(w_list[split_i - 1])
                diff = abs(acc - (total_chars - acc))
                if diff < best_diff:
                    best_diff, best_split = diff, split_i
            wrapped = [" ".join(w_list[:best_split]), " ".join(w_list[best_split:])]
    return display_title, wrapped


def layout_chapter_pages(
    ch: Chapter,
    idx: int,
    labels: BookLabels,
    fonts: Tuple[pymupdf.Font, pymupdf.Font, pymupdf.Font],
    page_dims: Tuple[float, float, float, float, float],
    bilingual: bool,
    include_back_to_toc: bool,
    compact: bool = False,
) -> Tuple[str, List[List[LineCmd]]]:
    """Calcula páginas e comandos tipográficos de um capítulo em folha A4."""
    font_reg, font_bold, font_ital = fonts
    page_w, page_h, margin_x, margin_top, margin_bottom = page_dims
    max_width = page_w - 2 * margin_x

    pages: List[List[LineCmd]] = [[]]
    y = margin_top + 34.0
    eff_mb = 40.0 if compact else margin_bottom
    body_lh, body_asc = (16.8, 13.4) if compact else (18.0, 14.2)
    body_desc = body_lh - body_asc
    para_gap, post_title_gap = (4.2, 28.0) if compact else (8.0, 36.0)

    def _ensure_space(needed_h: float) -> None:
        nonlocal y
        if y + needed_h > page_h - eff_mb:
            pages.append([])
            y = margin_top

    def _emit_lines(text: str, fnt: pymupdf.Font, fkind: str, fsize: float, lead: float, asc: float, color: Tuple[float, float, float]) -> None:
        nonlocal y
        desc = lead - asc
        for ln in wrap_pdf_text(text, fnt, fsize, max_width):
            _ensure_space(lead)
            y += asc
            pages[-1].append((y, ln, fkind, fsize, color, False))
            y += desc

    raw_ch_title = (ch.translated_title or ch.title).strip()
    display_title, heading_lines = prepare_chapter_heading(idx, raw_ch_title, labels.chapter_word, font_bold, 22.5, max_width)
    for ln in heading_lines:
        _ensure_space(28.0)
        y += 23.0
        pages[-1].append((y, ln, "bold", 22.5, (0.0, 0.0, 0.0), False))
        y += 5.0

    if bilingual and ch.translated_title and clean_pdf_text(ch.translated_title) != clean_pdf_text(ch.title):
        y += 4.0
        _emit_lines(ch.title.strip(), font_ital, "ital", 11.5, 16.0, 13.0, (0.3, 0.3, 0.3))

    y += post_title_gap
    for item in ch.items:
        orig_txt = clean_pdf_text(item.text)
        trans_txt = clean_pdf_text(item.translated_text or item.text)
        if not trans_txt:
            continue
        if item.kind in ("h2", "h3"):
            y += 10.0
            if bilingual and orig_txt != trans_txt:
                _emit_lines(orig_txt, font_ital, "ital", 10.5, 15.0, 12.0, (0.3, 0.3, 0.3))
            _emit_lines(trans_txt, font_ital, "ital", 14.0, 20.0, 16.0, (0.08, 0.08, 0.08))
            y += 6.0
        elif item.kind == "footnote":
            _emit_lines(trans_txt, font_reg, "reg", 10.0, 14.5, 11.5, (0.22, 0.22, 0.22))
            y += 4.0
        else:
            if bilingual:
                _emit_lines(orig_txt, font_ital, "ital", 10.5, 15.0, 12.0, (0.3, 0.3, 0.3))
                y += 2.5
            _emit_lines(trans_txt, font_reg, "reg", 12.5, body_lh, body_asc, (0.06, 0.06, 0.06))
            y += para_gap

    if include_back_to_toc:
        y += 10.0
        _ensure_space(22.0)
        y += 15.0
        pages[-1].append((y, f"[{labels.back_to_toc.lstrip('↑ ').strip()}]", "reg", 11.0, (0.0, 0.25, 0.65), True))

    if not compact and len(pages) >= 2:
        last_body = [cmd for cmd in pages[-1] if not cmd[5]]
        if 0 < len(last_body) <= 4:
            c_title, c_pages = layout_chapter_pages(ch, idx, labels, fonts, page_dims, bilingual, include_back_to_toc, compact=True)
            if len(c_pages) < len(pages):
                return c_title, c_pages
    return display_title, pages
