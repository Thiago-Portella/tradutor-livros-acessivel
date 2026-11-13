# Role: policy
"""Regras heurísticas puras para cabeçalhos, rodapés, notas e títulos em PDF."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from src.policies.text_normalizer import strip_control_chars, strip_page_brackets

CHAPTER_MARKER_RE = re.compile(
    r"^(?:\[\d+\]\s*)?(Chapter|Capítulo|Capitulo|Part|Parte|Book|Livro|Section|Seção|Secção)\s+"
    r"((?:the\s+)?(?:[0-9]+|[IVXLCDM]+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|"
    r"First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|"
    r"Um|Dois|Três|Quatro|Cinco|Seis|Sete|Oito|Nove|Dez|"
    r"Primeiro|Primeira|Segundo|Segunda|Terceiro|Terceira))\b[:.\-–—\s]*(.*)$",
    re.I,
)

STANDALONE_CHAPTER_TITLES_RE = re.compile(
    r"^(?:\[\d+\]\s*)?(Preâmbulo|Preambulo|Preamble|Contents|Table of Contents|Sumário|Sumario|"
    r"Índice|Indice|I\s+n\s+d\s+i\s+c\s+e|Introduction|Introdução|Preface|Prefácio|"
    r"Foreword|Apresentação|Apresentação da coleção|Lista de siglas e abreviaturas|"
    r"Prologue|Prólogo|Epilogue|Epílogo|Conclusion|Conclusão|"
    r"Afterword|Posfácio|Appendix|Apêndice|Bibliography|Bibliografia|References|Referências|"
    r"Notes|Notas|Glossary|Glossário|Index|Acknowledgements|Acknowledgments|Agradecimentos)[:.\-–—]*$",
    re.I,
)

ARTICLE_START_RE = re.compile(r"^(Art(?:icle|igo|ículo|\.)\s*[0-9]+[º°.]?)\b", re.I)
STANDALONE_ARTICLE_RE = re.compile(r"^Art(?:icle|igo|ículo|\.)\s*[0-9]+[º°.]?$", re.I)
NUMBERED_ITEM_START_RE = re.compile(r"^(\d{1,3}\.\s+\S+|\(\d{1,3}\)\s+\S+)")
TOC_DOT_LEADER_RE = re.compile(r"\.{3,}\s*\d{1,4}\s*$")

JUNK_META_TITLE_RE = re.compile(
    r"^(microsoft\s+word|microsoft\s+office|untitled|sem\s+t[íi]tulo|documento?\s*\d*|slide\s*\d*)"
    r"|\.(doc|docx|pdf|indd|qxd|qxp|odt|rtf|txt|ppt|pptx|pmd)$",
    re.I,
)

COVER_BOILERPLATE_RE = re.compile(
    r"^(working\s+people\s+of\s+the\s+whole\s+world|"
    r"trabalhadores\s+de\s+todo\s+o\s+mundo|"
    r"viva\s+a\s+rep[úu]blica\s+popular|"
    r"foreign\s+languages\s+publishing\s+house|"
    r"ediciones\s+en\s+lenguas\s+extranjeras|"
    r"pyongyang,\s*korea|juche\s+\d+|@\s*foreign\s+trade|@\s*editorial|"
    r"adopted\s+at\s+the\s+|aprovada\s+na\s+|nota\s+do\s+editor)",
    re.I,
)


def span_is_bold(span: dict) -> bool:
    font_name = (span.get("font") or "").lower()
    flags = int(span.get("flags", 0))
    return (
        bool(flags & 16)
        or "bold" in font_name
        or "cmbx" in font_name
        or "cmcsc" in font_name
        or "medi" in font_name
        or "black" in font_name
    )


def is_running_header_or_footer(
    bbox: Tuple[float, float, float, float],
    text: str,
    page_height: float,
    max_font_size: float = 0.0,
    body_font_size: float = 0.0,
) -> bool:
    """Detecta cabeçalhos de página repetitivos, rodapés e numeração solta."""
    _x0, y0, _x1, y1 = bbox
    cleaned = strip_control_chars(text).strip()
    if not cleaned:
        return True

    if re.fullmatch(r"\[\d+\](?:\s*-\s*\[\d+\])?", cleaned):
        return True

    if (
        CHAPTER_MARKER_RE.match(cleaned)
        or STANDALONE_CHAPTER_TITLES_RE.match(cleaned)
        or ARTICLE_START_RE.match(cleaned)
        or NUMBERED_ITEM_START_RE.match(cleaned)
    ):
        return False

    if y0 > page_height * 0.84 or y1 < page_height * 0.15:
        if re.fullmatch(r"[0-9]+|[ivxlcdmIVXLCDM]{1,6}", cleaned):
            return True

    is_display_scale = body_font_size > 0 and max_font_size >= body_font_size + 2.0

    if y1 < page_height * 0.15 and not is_display_scale:
        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
        if len(lines) <= 2:
            if any(re.fullmatch(r"[0-9]+|[ivxlcdmIVXLCDM]{1,6}", ln) for ln in lines):
                return True
            if re.match(r"^\d{1,4}\s+[A-Za-zÀ-ÿ]", cleaned):
                return True
            if (
                re.search(r"[A-Za-zÀ-ÿ?!)”\"']\s+\d{1,4}$", cleaned)
                and not TOC_DOT_LEADER_RE.search(cleaned)
            ):
                return True
            if y1 < page_height * 0.032 and len(cleaned) < 75:
                return True
            if (
                y1 < page_height * 0.085
                and len(cleaned) < 75
                and max_font_size > 0
                and body_font_size > 0
                and max_font_size <= body_font_size - 1.5
            ):
                return True

    if y0 > page_height * 0.85 and len(cleaned) < 45:
        if re.fullmatch(r"(Page\s+|Página\s+)?[0-9]+|[ivxlcdmIVXLCDM]{1,6}", cleaned, re.I):
            return True
        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
        if len(lines) == 2 and re.fullmatch(r"[0-9]{1,4}", lines[0]):
            return True
        if re.match(r"^\d{1,4}\s+\S+", cleaned):
            return True

    return False


def is_footnote_block(
    bbox: Tuple[float, float, float, float],
    text: str,
    max_font_size: float,
    body_font_size: float,
    page_height: float,
) -> bool:
    """Detecta blocos de notas de rodapé na metade inferior da página."""
    _x0, y0, _x1, _y1 = bbox
    cleaned = strip_control_chars(text).strip()
    if not cleaned:
        return False
    if len(cleaned) <= 6 and re.fullmatch(r"[0-9]+|[ivxlcdmIVXLCDM]{1,6}", cleaned):
        return False
    if re.match(
        r"^(Chapter|Capítulo|Capitulo|Part|Parte|Section|Seção|Art(?:icle|igo|ículo|\.)\s*\d+)\b",
        cleaned,
        re.I,
    ):
        return False

    is_smaller_font = max_font_size > 0 and max_font_size <= (body_font_size - 0.8)
    starts_with_note_marker = bool(
        re.match(r"^([0-9]{1,3}[a-zA-Z]?|\*+|†|‡)\s*[A-ZÀ-Úa-zà-ú“\"'‘]", cleaned)
    ) and not bool(re.match(r"^[0-9]{1,3}\.\s+", cleaned))

    if y0 > page_height * 0.55 and is_smaller_font:
        return True
    if y0 > page_height * 0.72 and starts_with_note_marker and max_font_size <= body_font_size:
        return True
    return False


def is_heading_candidate(
    text: str,
    max_font_size: float,
    is_bold: bool,
    fonts_in_block: List[str],
    body_font_size: float,
    chapter_title: str,
) -> Optional[str]:
    """Classifica unidade curta como 'skip' (título repetido), 'h2' (subtítulo) ou None."""
    cleaned = text.strip()
    if not cleaned or len(cleaned) > 150:
        return None

    cleaned_no_bracket = strip_page_brackets(cleaned)
    ch_no_bracket = strip_page_brackets(chapter_title) if chapter_title else ""

    if re.fullmatch(
        r"(Chapter|Capítulo|Capitulo|Parte|Part|Section|Seção)\s+[0-9IVXLCDM]+",
        cleaned_no_bracket,
        re.I,
    ):
        return "skip"
    if ch_no_bracket and cleaned_no_bracket.lower() == ch_no_bracket.lower():
        return "skip"
    if ch_no_bracket:
        stripped_ch = re.sub(
            r"^((Chapter|Capítulo|Capitulo|Parte|Part)\s+[0-9IVXLCDM]+[:.\-–—\s]*|\d+\.?\s*)",
            "",
            ch_no_bracket,
            flags=re.I,
        ).strip()
        if stripped_ch and stripped_ch.lower() == cleaned_no_bracket.lower():
            return "skip"

    if re.fullmatch(r"Art(?:icle|igo|ículo|\.)\s*[0-9]+[º°.]?", cleaned_no_bracket, re.I):
        return "h2"

    is_small_caps_or_bold = is_bold or any(
        ("CMCSC" in f or "CMBX" in f or "Bold" in f or "Medi" in f)
        for f in fonts_in_block
    )
    is_larger_font = max_font_size >= body_font_size + 1.2
    ends_like_heading = not cleaned_no_bracket.endswith((".", ",", ";"))

    if (
        (is_small_caps_or_bold or is_larger_font)
        and ends_like_heading
        and len(cleaned_no_bracket.split()) <= 20
    ):
        return "h2"
    return None
