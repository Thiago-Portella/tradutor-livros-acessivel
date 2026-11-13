# Role: policy
"""Camadas 3 a 5 de descoberta de capítulos e detecção de sumário impresso em PDF."""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Set, Tuple

from src.policies.pdf_chapter_layers_explicit import (
    LogicalUnit,
    try_explicit_or_numbered_layers,
)
from src.policies.pdf_heuristics import TOC_DOT_LEADER_RE
from src.policies.text_normalizer import format_all_caps_title


def detect_printed_toc_pages(
    pages_units: Dict[int, List[LogicalUnit]],
    total_pages: int,
) -> Tuple[Set[int], List[Tuple[str, int]]]:
    """Identifica páginas de sumário impresso e extrai suas entradas."""
    toc_pages: Set[int] = set()
    printed_entries: List[Tuple[str, int]] = []
    toc_header_re = re.compile(
        r"^(?:\[\d+\]\s*)?(Contents|Table of Contents|Sumário|Sumario|Índice|Indice|I\s*n\s*d\s*i\s*c\s*e)\b",
        re.I,
    )

    for pno in range(1, min(25, total_pages + 1)):
        p_units = pages_units.get(pno, [])
        if not p_units:
            continue
        has_hdr = any(toc_header_re.match(u.text) for u in p_units[:4])
        dot_cnt = sum(1 for u in p_units if TOC_DOT_LEADER_RE.search(u.text))
        brk_cnt = sum(1 for u in p_units if re.search(r"\[\d{1,4}\]\s*$", u.text))

        is_toc = (
            (has_hdr and (dot_cnt >= 1 or brk_cnt >= 2 or len(p_units) >= 4))
            or dot_cnt >= 3
            or ((pno - 1) in toc_pages and dot_cnt >= 1 and dot_cnt >= len(p_units) * 0.5)
        )
        if is_toc:
            toc_pages.add(pno)
            for u in p_units:
                m_dot = re.match(r"^(.+?)(?:\s*\.{2,}\s*|\s{3,})(\d{1,4})$", u.text.strip())
                if m_dot:
                    t_clean = m_dot.group(1).strip(" .")
                    if len(t_clean) >= 2:
                        printed_entries.append((t_clean, int(m_dot.group(2))))

    return toc_pages, printed_entries


def _discover_display_headings(
    body_units: List[LogicalUnit],
    body_font_size: float,
    consumed_heading_indices: Set[int],
    book_title: str = "",
) -> Tuple[List[Tuple[str, int]], Set[int]]:
    n_units = len(body_units)
    display_starts: List[Tuple[str, int]] = []
    consumed_display: Set[int] = set()
    noise_re = re.compile(
        r"(Tel:|Fax:|E-mail:|Dirección:|ISSN|@\s*Editorial|@\s*Foreign|Compre agora e leia|ISBN\s*\d|\.(com|org|net|br)\b)",
        re.I,
    )
    caption_ignore_re = re.compile(
        r"^(Perfumes|This on the\b|The Lamen\b|The Character of\b|Then bless\b|Oration lo be said\b)",
        re.I,
    )
    short_freq: Counter[str] = Counter(
        u.text.strip().lower().rstrip(".:") for u in body_units if len(u.text.strip()) <= 40
    )
    ad_pages: Set[int] = {
        u.page_num for u in body_units if re.search(r"compre\s+agora\s+e\s+leia", u.text, re.I)
    }
    norm_book_title = re.sub(r"\s+", " ", (book_title or "").strip().lower())

    k = 0
    while k < n_units:
        if k in consumed_heading_indices:
            k += 1
            continue
        u = body_units[k]
        u_txt = u.text.strip()
        u_key = u_txt.lower().rstrip(".:")

        is_large = u.max_font_size >= body_font_size + 2.5 and (
            not u_txt.endswith(".")
            or u_txt.isupper()
            or bool(re.match(r"^(CHARACTER|CHABACTER|CRARACTER)\b", u_txt, re.I))
        )
        is_bold_hdr = (u.is_bold or bool(re.match(r"^(Form of a\b|Oration\b)", u_txt, re.I))) and (
            u.max_font_size >= body_font_size + 1.2
            or (short_freq[u_key] <= 2 and not u_txt.endswith((".", ";", "!")) and len(u_txt.split()) <= 16)
        )

        if (
            u.page_num > 1
            and u.page_num not in ad_pages
            and (u.page_num - 1) not in ad_pages
            and (is_large or is_bold_hdr)
            and 4 <= len(u_txt) <= 95
            and not noise_re.search(u_txt)
            and not caption_ignore_re.search(u_txt)
            and not re.fullmatch(r"\d+", u_txt)
        ):
            parts = [u_txt.rstrip(".:")]
            temp_consumed = {k}
            m_k = k + 1
            while is_large and m_k < n_units and m_k <= k + 3 and body_units[m_k].page_num == u.page_num and m_k not in consumed_heading_indices:
                nxt = body_units[m_k]
                if (
                    nxt.max_font_size >= body_font_size + 2.5
                    and (abs(nxt.max_font_size - u.max_font_size) <= 12.0 or (u.max_font_size >= body_font_size + 8.0 and nxt.max_font_size >= body_font_size + 8.0))
                    and (nxt.bbox[1] - body_units[m_k - 1].bbox[3]) < 75.0
                    and len(nxt.text) <= 95
                    and not nxt.text.endswith(".")
                ):
                    if nxt.text.lower() != parts[-1].lower():
                        parts.append(nxt.text.rstrip(".:"))
                    temp_consumed.add(m_k)
                    m_k += 1
                else:
                    break

            combined = format_all_caps_title(" ".join(parts).strip())
            is_colophon = any(
                "©" in o.text or "Dados Internacionais de Catalogação" in o.text or "copyright" in o.text.lower()
                for o in body_units[max(0, k - 2): min(n_units, m_k + 5)]
                if o.page_num == u.page_num
            )
            repeats_book_title = bool(norm_book_title and combined.lower() == norm_book_title)
            has_body_after_p2 = any(
                o.page_num == u.page_num and len(o.text.split()) >= 6
                for o in body_units[m_k: min(n_units, m_k + 4)]
            )

            # Permite capítulos legítimos na página 2 mesmo em livros longos quando há corpo textual real
            allow_page2 = (u.page_num == 2 and not repeats_book_title and has_body_after_p2)
            if len(combined) >= 4 and not is_colophon and (u.page_num > 2 or allow_page2):
                consumed_display.update(temp_consumed)
                display_starts.append((combined, k))
            k = m_k
            continue
        k += 1

    return display_starts, consumed_display


def discover_chapters_from_units(
    body_units: List[LogicalUnit],
    body_font_size: float,
    printed_entries: List[Tuple[str, int]],
    toc_pages: Set[int],
    p_start: int,
    p_end: int,
    book_title: str = "",
) -> Tuple[List[Tuple[str, int, int]], Set[int], str]:
    """Descobre fronteiras de capítulos usando camadas explícitas, tipográficas, sumário impresso ou blocos."""
    n_units = len(body_units)
    if n_units == 0:
        return [], set(), "single_section"

    early_res, dedup_explicit, consumed_explicit = try_explicit_or_numbered_layers(
        body_units, body_font_size, toc_pages, p_start, p_end
    )
    if early_res is not None:
        return early_res

    display_starts, consumed_display = _discover_display_headings(
        body_units, body_font_size, consumed_explicit, book_title=book_title
    )
    combined_map: Dict[int, str] = {u_idx: t for t, u_idx in dedup_explicit}
    for t, u_idx in display_starts:
        combined_map.setdefault(u_idx, t)

    merged_starts = [(combined_map[idx_k], idx_k) for idx_k in sorted(combined_map)]
    all_consumed = consumed_explicit | consumed_display

    consolidated: List[Tuple[str, int]] = []
    idx_m = 0
    while idx_m < len(merged_starts):
        ch_t, start_u = merged_starts[idx_m]
        if idx_m + 1 < len(merged_starts):
            next_t, next_u = merged_starts[idx_m + 1]
            if not any(u_i not in all_consumed for u_i in range(start_u, next_u)):
                merged_starts[idx_m + 1] = (f"{ch_t} — {next_t}", start_u)
                idx_m += 1
                continue
        consolidated.append((ch_t, start_u))
        idx_m += 1

    if len(consolidated) >= 2:
        spans: List[Tuple[str, int, int]] = []
        first_u = consolidated[0][1]
        if first_u > 0:
            pre_units = body_units[:first_u]
            pre_words = sum(len(u.text.split()) for u in pre_units)
            if not (all(u.page_num == p_start for u in pre_units) and pre_words < 35):
                spans.append(("Informações Iniciais", 0, first_u))
            else:
                all_consumed.update(range(0, first_u))
        for idx_s, (ch_title, start_u) in enumerate(consolidated):
            end_u = consolidated[idx_s + 1][1] if idx_s + 1 < len(consolidated) else n_units
            if start_u < end_u:
                spans.append((ch_title, start_u, end_u))
        return spans, all_consumed, "heuristic_typography"

    if len(printed_entries) >= 3:
        last_toc_pg = max(toc_pages) if toc_pages else 1
        offset = max(0, last_toc_pg - printed_entries[0][1] + 1)
        mapped: List[Tuple[str, int]] = []
        for entry_title, entry_pg in printed_entries:
            target_pg = entry_pg + offset
            found = next((idx_u for idx_u, u in enumerate(body_units) if u.page_num >= target_pg), None)
            if found is not None and (not mapped or found > mapped[-1][1]):
                mapped.append((entry_title, found))
        if len(mapped) >= 2:
            spans = [("Informações Iniciais", 0, mapped[0][1])] if mapped[0][1] > 0 else []
            for idx_s, (ch_title, start_u) in enumerate(mapped):
                end_u = mapped[idx_s + 1][1] if idx_s + 1 < len(mapped) else n_units
                if start_u < end_u:
                    spans.append((ch_title, start_u, end_u))
            return spans, set(), "printed_toc_parser"

    spans = []
    for part_idx, pg in enumerate(range(p_start, p_end + 1, 12), start=1):
        c_end = min(p_end, pg + 11)
        u_indices = [idx_u for idx_u, u in enumerate(body_units) if pg <= u.page_num <= c_end]
        if u_indices:
            spans.append((f"Parte {part_idx} (Páginas {pg} a {c_end})", u_indices[0], u_indices[-1] + 1))
    return spans, set(), "smart_page_chunks"
