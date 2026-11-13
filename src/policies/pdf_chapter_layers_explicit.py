# Role: policy
"""Camadas 1 e 2 de descoberta de capítulos (marcadores explícitos e tópicos numerados)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

from src.policies.pdf_heuristics import (
    ARTICLE_START_RE,
    CHAPTER_MARKER_RE,
    NUMBERED_ITEM_START_RE,
    STANDALONE_CHAPTER_TITLES_RE,
    TOC_DOT_LEADER_RE,
)
from src.policies.text_normalizer import format_all_caps_title, strip_page_brackets


@dataclass
class LogicalUnit:
    page_num: int
    bbox: Tuple[float, float, float, float]
    raw_text: str
    text: str
    max_font_size: float
    is_bold: bool
    all_bold: bool
    fonts: List[str]


def collect_explicit_chapter_starts(
    body_units: List[LogicalUnit],
    body_font_size: float,
) -> Tuple[List[Tuple[str, int]], Set[int]]:
    """Coleta marcadores explícitos ('Capítulo N', 'Introduction', etc.) nas unidades."""
    n_units = len(body_units)
    explicit_starts: List[Tuple[str, int]] = []
    consumed_indices: Set[int] = set()
    i = 0

    while i < n_units:
        u = body_units[i]
        txt_clean = strip_page_brackets(u.text)

        if not TOC_DOT_LEADER_RE.search(txt_clean):
            m_chap = CHAPTER_MARKER_RE.match(txt_clean)
            if (
                m_chap
                and len(txt_clean) <= 120
                and not txt_clean.endswith((",", ";"))
                and (not txt_clean.endswith(".") or txt_clean.isupper() or u.is_bold)
            ):
                prefix_word = m_chap.group(1)
                chap_num = m_chap.group(2)
                rest_title = m_chap.group(3).strip().rstrip(".")
                is_valid = (
                    (not rest_title or rest_title[0].isupper() or rest_title[0].isdigit())
                    and (
                        not rest_title
                        or txt_clean.isupper()
                        or u.is_bold
                        or u.all_bold
                        or u.max_font_size >= body_font_size + 1.2
                    )
                )
                if is_valid:
                    consumed_indices.add(i)
                    extra_parts: List[str] = [rest_title] if rest_title else []
                    j = i + 1
                    while j < n_units and j <= i + 3 and body_units[j].page_num == u.page_num:
                        nxt = body_units[j]
                        nxt_txt = strip_page_brackets(nxt.text)
                        if (
                            CHAPTER_MARKER_RE.match(nxt_txt)
                            or STANDALONE_CHAPTER_TITLES_RE.match(nxt_txt)
                            or ARTICLE_START_RE.match(nxt_txt)
                            or NUMBERED_ITEM_START_RE.match(nxt_txt)
                            or TOC_DOT_LEADER_RE.search(nxt_txt)
                        ):
                            break
                        is_sub_style = nxt_txt.isupper() or nxt.all_bold or nxt.max_font_size >= body_font_size + 1.5
                        if is_sub_style and len(nxt_txt) <= 95 and not nxt_txt.endswith((".", ";", "!")):
                            extra_parts.append(nxt_txt)
                            consumed_indices.add(j)
                            j += 1
                        else:
                            break

                    subtitle_str = format_all_caps_title(" ".join(extra_parts).strip())
                    prefix_fmt = format_all_caps_title(f"{prefix_word} {chap_num}")
                    if re.fullmatch(r"[IVXLCDM]+", chap_num, re.I):
                        prefix_fmt = f"{prefix_word.capitalize()} {chap_num.upper()}"
                    full_title = f"{prefix_fmt}: {subtitle_str}" if subtitle_str else prefix_fmt
                    explicit_starts.append((full_title, i))
                    i = j
                    continue

            if STANDALONE_CHAPTER_TITLES_RE.match(txt_clean):
                if u.is_bold or u.all_bold or u.max_font_size >= body_font_size + 1.2 or txt_clean.isupper():
                    consumed_indices.add(i)
                    explicit_starts.append((format_all_caps_title(txt_clean.rstrip(".:-–— ")), i))
                    i += 1
                    continue
        i += 1

    dedup: List[Tuple[str, int]] = []
    for title, u_idx in explicit_starts:
        if not dedup or dedup[-1][0].lower() != title.lower():
            dedup.append((title, u_idx))
    return dedup, consumed_indices


def try_explicit_or_numbered_layers(
    body_units: List[LogicalUnit],
    body_font_size: float,
    toc_pages: Set[int],
    p_start: int,
    p_end: int,
) -> Tuple[Optional[Tuple[List[Tuple[str, int, int]], Set[int], str]], List[Tuple[str, int]], Set[int]]:
    """Tenta resolver capítulos pelas Camadas 1 (explícitos) e 2 (tópicos numerados)."""
    n_units = len(body_units)
    dedup_explicit, consumed_explicit = collect_explicit_chapter_starts(body_units, body_font_size)

    first_pg = body_units[dedup_explicit[0][1]].page_num if dedup_explicit else p_end + 1
    starts_early = first_pg <= p_start + max(8, int((p_end - p_start) * 0.40))
    explicit_pages = [body_units[u_idx].page_num for _t, u_idx in dedup_explicit] + [p_end]
    max_gap = max((explicit_pages[k + 1] - explicit_pages[k] for k in range(len(explicit_pages) - 1)), default=0) if dedup_explicit else (p_end - p_start)

    if starts_early and (
        len(dedup_explicit) >= 5
        or (len(dedup_explicit) >= 2 and max_gap <= 8)
        or (len(dedup_explicit) == 1 and (p_end - p_start) <= 15)
    ):
        spans: List[Tuple[str, int, int]] = []
        if dedup_explicit[0][1] > 0:
            spans.append(("Informações Iniciais", 0, dedup_explicit[0][1]))
        for idx_s, (ch_title, start_u) in enumerate(dedup_explicit):
            end_u = dedup_explicit[idx_s + 1][1] if idx_s + 1 < len(dedup_explicit) else n_units
            if start_u < end_u:
                spans.append((ch_title, start_u, end_u))
        return (spans, consumed_explicit, "heuristic_typography"), dedup_explicit, consumed_explicit

    # Camada 2: Seções numeradas sequenciais em negrito
    numbered_candidates: List[Tuple[int, str, int]] = []
    numbered_re = re.compile(r"^(\d{1,3})\.\s+([A-ZÀ-Ú“\"‘'0-9].*)$")
    for idx_u, u in enumerate(body_units):
        if u.page_num <= 2 and toc_pages:
            continue
        if (u.all_bold or (u.is_bold and u.max_font_size >= body_font_size + 0.5)) and len(u.text) <= 130:
            if not u.text.endswith((".", ";", "!", "?")):
                m_num = numbered_re.match(u.text.strip())
                if m_num:
                    numbered_candidates.append((int(m_num.group(1)), u.text.strip(), idx_u))

    seq_numbered: List[Tuple[int, str, int]] = []
    for t_num, t_title, u_idx in numbered_candidates:
        if not seq_numbered:
            if 1 <= t_num <= 3:
                seq_numbered.append((t_num, t_title, u_idx))
        elif 1 <= (t_num - seq_numbered[-1][0]) <= 5:
            seq_numbered.append((t_num, t_title, u_idx))

    if len(seq_numbered) >= 4:
        consumed_num = {u_idx for _n, _t, u_idx in seq_numbered}
        spans = []
        if seq_numbered[0][2] > 0:
            spans.append(("Informações Iniciais", 0, seq_numbered[0][2]))
        for idx_s, (_tn, ch_title, start_u) in enumerate(seq_numbered):
            end_u = seq_numbered[idx_s + 1][2] if idx_s + 1 < len(seq_numbered) else n_units
            if start_u < end_u:
                spans.append((ch_title, start_u, end_u))
        return (spans, consumed_num, "heuristic_typography"), dedup_explicit, consumed_explicit

    return None, dedup_explicit, consumed_explicit
