# Role: policy
"""Políticas puras de normalização tipográfica, reflow de frases e limpeza de títulos."""

from __future__ import annotations

import re
import unicodedata
from typing import List

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LIGATURE_SPACE_RE = re.compile(r"([\ufb00-\ufb06])[ \t]+([a-zà-ÿ])")

_LIGATURE_MAP = str.maketrans(
    {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\ufb05": "st",
        "\ufb06": "st",
        "\u00ad": "",
        "\u200b": "",
        "\ufeff": "",
    }
)


def strip_control_chars(text: str) -> str:
    if not text:
        return ""
    return _CONTROL_CHARS_RE.sub("", text)


def clean_text_for_translate(text: str) -> str:
    if not text:
        return ""
    cleaned = strip_control_chars(text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    return cleaned.strip()


def normalize_typography(text: str, enabled: bool = True) -> str:
    """Substitui ligaturas tipográficas do LaTeX/PDF e normaliza espaços."""
    if not text:
        return ""
    text = strip_control_chars(text)
    if not enabled:
        return text.strip()
    text = _LIGATURE_SPACE_RE.sub(r"\1\2", text)
    text = text.translate(_LIGATURE_MAP)
    text = unicodedata.normalize("NFKC", text)
    return text


def reflow_lines_in_block(
    raw_text: str,
    do_normalize: bool = True,
    do_reflow: bool = True,
) -> str:
    """Reconstrói um parágrafo unindo palavras hifenizadas e linhas simples."""
    text = normalize_typography(raw_text.strip(), enabled=do_normalize)
    if not text:
        return ""
    if not do_reflow:
        return text.strip()

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    merged: List[str] = []
    for line in lines:
        if not merged:
            merged.append(line)
            continue
        prev = merged[-1]
        if (
            prev.endswith("-")
            and not prev.endswith("--")
            and not prev.endswith("—")
            and len(prev) >= 2
            and prev[-2].isalpha()
            and line
            and line[0].islower()
        ):
            merged[-1] = prev[:-1] + line
        else:
            merged.append(line)

    result = " ".join(merged)
    return re.sub(r"[ \t]{2,}", " ", result).strip()


def should_merge_paragraphs(prev_text: str, curr_text: str) -> bool:
    if not prev_text or not curr_text:
        return False
    prev = prev_text.rstrip()
    curr = curr_text.lstrip()
    if re.match(
        r"^(\([0-9a-zA-Z]+\)|[0-9]+\.|[•\-–—]|Art(?:icle|igo|ículo|\.)\s*[0-9]+)\s",
        curr,
        re.I,
    ):
        return False

    terminal_chars = (".", "!", "?", ":", ";", "”", "’", "'", '"', ")", "]")
    if prev.endswith("-") or not prev.endswith(terminal_chars):
        return True
    if curr and curr[0].islower():
        return True
    return False


def merge_two_texts(prev_text: str, curr_text: str) -> str:
    prev = prev_text.rstrip()
    curr = curr_text.lstrip()
    if (
        prev.endswith("-")
        and not prev.endswith("--")
        and len(prev) >= 2
        and prev[-2].isalpha()
        and curr
        and curr[0].islower()
    ):
        return prev[:-1] + curr
    return prev + " " + curr


def strip_page_brackets(text: str) -> str:
    return re.sub(r"^\[\d+\]\s*", "", text.strip())


def clean_heading_ocr_typos(text: str) -> str:
    t = re.sub(r"\b(?:CHABACTER|CRARACTER)\b", "CHARACTER", text, flags=re.I)
    t = re.sub(r"\bJ3ETHOR\b", "BETHOR", t, flags=re.I)
    t = re.sub(r"\bPRALEG\b", "PHALEG", t, flags=re.I)
    t = re.sub(r"\bSA\s+TURN\b", "SATURN", t, flags=re.I)
    t = re.sub(r"\bSymbois\.?\s+Circles\b", "Symbolic Circles", t, flags=re.I)
    t = re.sub(r"\bAro\s+Exorcisms\s+of\s+Tree\s+Band\b", "And Exorcisms of Three Bands", t, flags=re.I)
    t = re.sub(r"\bSpirits\.\s+Messengers\.", "Spirits, Messengers,", t, flags=re.I)
    return t


def format_all_caps_title(raw_title: str) -> str:
    """Formata títulos inteiramente em caixa alta preservando siglas conhecidas."""
    cleaned = clean_heading_ocr_typos(re.sub(r"\s+", " ", raw_title).strip())
    if len(cleaned) <= 5:
        return cleaned
    alpha_chars = [c for c in cleaned if c.isalpha()]
    upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) if alpha_chars else 0.0
    small_words = {
        "of", "the", "and", "in", "on", "for", "to", "with", "by", "at", "from",
        "de", "da", "do", "das", "dos", "e", "em", "na", "no", "nas", "nos",
        "para", "com", "a", "o", "la", "el", "los", "las", "del", "y", "en",
    }
    acronyms = {"RPDC", "DPRK", "EUA", "URSS", "ONU", "UNESCO"}
    if not cleaned.isupper() and upper_ratio < 0.72:
        words_mixed = cleaned.split()
        norm_mixed: List[str] = []
        for idx_w, w in enumerate(words_mixed):
            w_strip = w.strip(".,:;!?”\"'()")
            if len(w_strip) >= 4 and w_strip.isalpha() and w_strip.isupper() and w_strip not in acronyms:
                prefix_p = "(" if w.startswith("(") else ""
                suffix_p = w[len(prefix_p) + len(w_strip):]
                norm_mixed.append(f"{prefix_p}{w_strip[0]}{w_strip[1:].lower()}{suffix_p}")
            elif idx_w > 0 and w_strip.lower() in small_words and not words_mixed[idx_w - 1].endswith((":", "—", "-")):
                norm_mixed.append(w.lower())
            else:
                norm_mixed.append(w)
        return " ".join(norm_mixed)

    out: List[str] = []
    for i, w in enumerate(cleaned.split()):
        w_clean = w.strip(".,:;()[]\"'“”")
        if w_clean in acronyms:
            out.append(w)
        elif i > 0 and w.lower() in small_words:
            out.append(w.lower())
        else:
            parts = re.split(r"([’'\-])", w)
            formatted_parts = [
                p.capitalize() if idx == 0 or parts[idx - 1] == "-" else p.lower()
                for idx, p in enumerate(parts)
            ]
            out.append("".join(formatted_parts))
    return " ".join(out)
