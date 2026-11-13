# Role: policy
"""Políticas de extração de metadados de capa e fonte dominante em PDFs."""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import List, Tuple

import pymupdf

from src.policies.pdf_heuristics import COVER_BOILERPLATE_RE, JUNK_META_TITLE_RE
from src.policies.text_normalizer import (
    format_all_caps_title,
    normalize_typography,
    strip_control_chars,
)

_GENERIC_AUTHORS = {
    "admin", "administrator", "administrador", "user", "usuario", "usuário",
    "owner", "proprietário", "pc", "microsoft", "unknown",
}


def _collect_cover_lines(doc: pymupdf.Document) -> List[Tuple[int, float, float, str]]:
    cover_lines: List[Tuple[int, float, float, str]] = []
    for p_idx in range(min(2, len(doc))):
        d = doc[p_idx].get_text("dict")
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            for l in b.get("lines", []):
                lt = normalize_typography(
                    "".join(s.get("text", "") for s in l.get("spans", []))
                ).strip()
                if not lt or COVER_BOILERPLATE_RE.search(lt):
                    continue
                sz = max((float(s.get("size", 0)) for s in l.get("spans", [])), default=0.0)
                y0 = float(l["bbox"][1])
                if y0 < 25.0 and sz < 13.0:
                    continue
                cover_lines.append((p_idx, y0, sz, lt))
    return cover_lines


def guess_pdf_book_metadata(doc: pymupdf.Document, pdf_path: str) -> Tuple[str, str]:
    """Infere título e autor reais combinando metadados do PDF e capa/rosto."""
    meta = doc.metadata or {}
    title = normalize_typography(meta.get("title") or "").strip()
    author = normalize_typography(meta.get("author") or "").strip()

    if (
        not title
        or len(title) < 3
        or JUNK_META_TITLE_RE.search(title)
        or re.search(r"[\u3000-\u9fff\uac00-\ud7af]", title)
    ):
        title = ""

    if author and (len(author) < 2 or author.lower() in _GENERIC_AUTHORS):
        author = ""

    if not title and len(doc) >= 2:
        p2_text = normalize_typography(doc[1].get_text("text"))
        m = re.search(r"([A-Z][A-Za-z0-9 ,:;\-’'?]+?)\s+was published in\s+\d{4}", p2_text)
        if m:
            title = m.group(1).strip(" ?")
        m_auth = re.search(r"copyright\s+([A-Z][A-Za-z. ,]+?)\.", p2_text)
        if m_auth and not author:
            author = m_auth.group(1).strip()

    if len(doc) >= 1:
        cover_lines = _collect_cover_lines(doc)
        p1_lines = [x for x in cover_lines if x[0] == 0]
        target_lines = p1_lines if p1_lines else cover_lines

        if not title:
            joined_uk = " ".join(x[3] for x in target_lines)
            m_uk = re.search(r"UNDERSTANDING\s+KOREA\s+(\d+)\s+([A-Z &,\-]+)", joined_uk, re.I)
            if m_uk:
                title = f"Understanding Korea {m_uk.group(1).strip()}: {format_all_caps_title(m_uk.group(2).strip())}"
                if not author:
                    author = "Foreign Languages Publishing House"

        if not title and target_lines:
            known_authors = ("KIM IL SUNG", "KIM JONG IL", "KIM JONG UN")
            if target_lines[0][3].upper() in known_authors and len(target_lines) >= 2:
                if not author:
                    author = format_all_caps_title(target_lines[0][3])
                rem = [x for x in target_lines[1:] if x[2] >= 14.0]
                if rem:
                    max_rem_sz = max(x[2] for x in rem)
                    title = format_all_caps_title(" ".join(x[3] for x in rem if x[2] >= max_rem_sz - 3.0))

        if target_lines:
            prominent = [x for x in target_lines if x[2] >= 16.0 and not re.fullmatch(r"\d+", x[3])]
            if prominent:
                max_sz = max(x[2] for x in prominent)
                raw_candidates = [txt for _p, _y, sz, txt in prominent if sz >= max_sz - 4.5]
                title_parts: List[str] = []
                for txt in raw_candidates:
                    if len(txt) >= 4 and any(
                        txt.lower() != other.lower() and txt.lower() in other.lower()
                        for other in raw_candidates
                    ):
                        continue
                    if not title_parts or txt.lower() != title_parts[-1].lower():
                        title_parts.append(txt)
                candidate = format_all_caps_title(" ".join(title_parts))
                if 4 <= len(candidate) <= 150:
                    if not title or (title.isupper() and title.lower() in candidate.lower() and len(candidate) > len(title)):
                        title = format_all_caps_title(candidate)
                    elif title.isupper():
                        title = format_all_caps_title(title)

    if not title:
        base = os.path.splitext(os.path.basename(pdf_path))[0]
        title = base.replace("_", " ").replace("-", " ").title()
    if not author:
        author = "Autor Desconhecido"
    return title, author


def estimate_body_font_size(doc: pymupdf.Document) -> float:
    """Estima o tamanho da fonte predominante do corpo do texto."""
    total_pages = len(doc)
    font_sizes: Counter[float] = Counter()
    step = max(1, total_pages // 20)
    for sp in range(0, total_pages, step):
        d = doc[sp].get_text("dict")
        for b in d.get("blocks", []):
            if b.get("type") == 0:
                for l in b.get("lines", []):
                    for s in l.get("spans", []):
                        txt = strip_control_chars(s.get("text", "")).strip()
                        if len(txt) > 5:
                            sz = round(float(s.get("size", 10.0)), 1)
                            font_sizes[sz] += len(txt)
    return font_sizes.most_common(1)[0][0] if font_sizes else 10.0
