"""
Extrator e aprimorador inteligente de livros (PDF, EPUB, TXT, MD) com controles granulares:
- Normalização tipográfica e de caracteres (ligaturas ﬁ/ﬀ/ﬂ com correção de espaço espúrio,
  remoção de caracteres de controle, hifens invisíveis, espaços múltiplos)
- Divisão inteligente de blocos do PDF em unidades lógicas (separando títulos de capítulos,
  artigos de leis/constituições, subtítulos em negrito e itens numerados que o PDF agrupou)
- Reconstrução de frases e parágrafos (des-hifenização de fim de linha e união de parágrafos
  cortados no meio da frase entre linhas ou viradas de página)
- Remoção de cabeçalhos e rodapés repetitivos / números de página soltos
- Tratamento configurável de notas de rodapé na base da página:
  * 'move_end': move para uma subseção 'Notas do Capítulo' no fim do capítulo (não interrompe a frase!)
  * 'remove': remove as notas de rodapé completamente
  * 'keep': mantém na posição original
- Organização e descoberta automática de Sumário / Capítulos em múltiplas camadas, incluindo
  suporte a capítulos que começam no meio da página ou múltiplos capítulos na mesma página.
"""

from __future__ import annotations

import os
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import pymupdf


@dataclass
class EnhancementOptions:
    """Opções granulares de aprimoramento estrutural e textual do livro."""

    normalize_chars: bool = True
    reflow_sentences: bool = True
    remove_headers_footers: bool = True
    organize_toc: bool = True
    force_heuristic_toc: bool = False
    footnote_mode: str = "move_end"  # "move_end", "remove", "keep"
    include_back_to_toc: bool = False


@dataclass
class ParagraphItem:
    text: str
    kind: str = "p"  # "p", "h2", "h3", "blockquote", "list_item", "footnote"
    page_number: int = 1
    translated_text: Optional[str] = None


@dataclass
class Chapter:
    index: int
    title: str
    start_page: int
    end_page: int
    translated_title: Optional[str] = None
    items: List[ParagraphItem] = field(default_factory=list)


@dataclass
class BookStructure:
    title: str
    author: str
    source_path: str
    chapters: List[Chapter] = field(default_factory=list)
    toc_discovery_method: str = "embedded"


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
        "\u00ad": "",  # soft hyphen
        "\u200b": "",  # zero-width space
        "\ufeff": "",  # BOM
    }
)


def strip_control_chars(text: str) -> str:
    if not text:
        return ""
    return _CONTROL_CHARS_RE.sub("", text)


def normalize_typography(text: str, enabled: bool = True) -> str:
    """Substitui ligaturas tipográficas do LaTeX/PDF, remove caracteres de controle e normaliza espaços."""
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
    """
    Reconstrói um parágrafo a partir das linhas de uma unidade lógica de PDF:
    - Une palavras hifenizadas no fim da linha (ex: 'de-\\nmocratic' -> 'democratic')
    - Substitui quebras de linha simples por espaços
    """
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
    result = re.sub(r"[ \t]{2,}", " ", result)
    return result.strip()


def _is_running_header_or_footer(
    bbox: Tuple[float, float, float, float],
    text: str,
    page_height: float,
    chapter_title: str = "",
    max_font_size: float = 0.0,
    body_font_size: float = 0.0,
) -> bool:
    """
    Detecta cabeçalhos de página (running headers) e rodapés/números de página soltos.
    """
    _x0, y0, _x1, y1 = bbox
    cleaned = strip_control_chars(text).strip()
    if not cleaned:
        return True

    # Marcadores de página de edição impressa isolados (ex: "[12]-[13]")
    if re.fullmatch(r"\[\d+\](?:\s*-\s*\[\d+\])?", cleaned):
        return True

    # Nunca remover títulos de capítulos, seções numeradas ("6. Mt Paektu") ou artigos no topo da página
    if (
        _CHAPTER_MARKER_RE.match(cleaned)
        or _STANDALONE_CHAPTER_TITLES_RE.match(cleaned)
        or _ARTICLE_START_RE.match(cleaned)
        or _NUMBERED_ITEM_START_RE.match(cleaned)
    ):
        return False

    if y0 > page_height * 0.84 or y1 < page_height * 0.15:
        if re.fullmatch(r"[0-9]+|[ivxlcdmIVXLCDM]{1,6}", cleaned):
            return True

    if y1 < page_height * 0.15:
        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
        if len(lines) <= 2:
            has_page_num = any(
                re.fullmatch(r"[0-9]+|[ivxlcdmIVXLCDM]{1,6}", ln) for ln in lines
            )
            if has_page_num:
                return True
            # Cabeçalho com número de página na esquerda ("14 Chapter 1...") ou na direita ("Introduction 3")
            if re.match(r"^\d{1,4}\s+[A-Za-zÀ-ÿ]", cleaned):
                return True
            if (
                re.search(r"[A-Za-zÀ-ÿ?!)”\"']\s+\d{1,4}$", cleaned)
                and not _TOC_DOT_LEADER_RE.search(cleaned)
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
        # Rodapé de revista com número de página + nome da publicação (ex: "2\nComercio Exterior de la RPDC")
        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
        if len(lines) == 2 and re.fullmatch(r"[0-9]{1,4}", lines[0]):
            return True
        if re.match(r"^\d{1,4}\s+\S+", cleaned):
            return True

    return False


def _is_footnote_block(
    bbox: Tuple[float, float, float, float],
    text: str,
    max_font_size: float,
    body_font_size: float,
    page_height: float,
) -> bool:
    """
    Detecta blocos de notas de rodapé (footnotes) na parte inferior da página.
    """
    _x0, y0, _x1, _y1 = bbox
    cleaned = strip_control_chars(text).strip()
    if not cleaned:
        return False

    if len(cleaned) <= 6 and re.fullmatch(r"[0-9]+|[ivxlcdmIVXLCDM]{1,6}", cleaned):
        return False

    # Não tratar títulos de capítulos ou artigos no fim da página como nota de rodapé
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


def _strip_page_brackets(text: str) -> str:
    """Remove marcadores de página entre colchetes no início de títulos, ex: '[27] 1. Nacionalismo'."""
    return re.sub(r"^\[\d+\]\s*", "", text.strip())


def _is_heading_candidate(
    text: str,
    max_font_size: float,
    is_bold: bool,
    fonts_in_block: List[str],
    body_font_size: float,
    chapter_title: str,
) -> Optional[str]:
    """
    Verifica se uma unidade lógica curta na página é um título ou subtítulo (h2 / h3).
    Retorna 'skip' se for repetição do título do capítulo, 'h2' se for subtítulo, ou None se for parágrafo.
    """
    cleaned = text.strip()
    if not cleaned or len(cleaned) > 150:
        return None

    cleaned_no_bracket = _strip_page_brackets(cleaned)
    ch_no_bracket = _strip_page_brackets(chapter_title) if chapter_title else ""

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

    # Marcador isolado de Artigo (ex: "Artigo 1", "Artículo 138")
    if re.fullmatch(r"Art(?:icle|igo|ículo|\.)\s*[0-9]+[º°.]?", cleaned_no_bracket, re.I):
        return "h2"

    is_small_caps_or_bold = is_bold or any(
        ("CMCSC" in f or "CMBX" in f or "Bold" in f or "Medi" in f)
        for f in fonts_in_block
    )
    is_larger_font = max_font_size >= body_font_size + 1.2

    ends_like_heading = (
        not cleaned_no_bracket.endswith(".")
        and not cleaned_no_bracket.endswith(",")
        and not cleaned_no_bracket.endswith(";")
    )

    if (
        (is_small_caps_or_bold or is_larger_font)
        and ends_like_heading
        and len(cleaned_no_bracket.split()) <= 20
    ):
        return "h2"

    return None


def _should_merge_paragraphs(prev_text: str, curr_text: str) -> bool:
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
    if prev.endswith("-"):
        return True
    if not prev.endswith(terminal_chars):
        return True
    if curr and curr[0].islower():
        return True

    return False


def _merge_two_texts(prev_text: str, curr_text: str) -> str:
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


_JUNK_META_TITLE_RE = re.compile(
    r"^(microsoft\s+word|microsoft\s+office|untitled|sem\s+t[íi]tulo|documento?\s*\d*|slide\s*\d*)"
    r"|\.(doc|docx|pdf|indd|qxd|qxp|odt|rtf|txt|ppt|pptx|pmd)$",
    re.I,
)

_COVER_BOILERPLATE_RE = re.compile(
    r"^(working\s+people\s+of\s+the\s+whole\s+world|"
    r"trabalhadores\s+de\s+todo\s+o\s+mundo|"
    r"viva\s+a\s+rep[úu]blica\s+popular|"
    r"foreign\s+languages\s+publishing\s+house|"
    r"ediciones\s+en\s+lenguas\s+extranjeras|"
    r"pyongyang,\s*korea|"
    r"juche\s+\d+|"
    r"@\s*foreign\s+trade|@\s*editorial|"
    r"adopted\s+at\s+the\s+|aprovada\s+na\s+|"
    r"nota\s+do\s+editor)",
    re.I,
)


def _clean_heading_ocr_typos(text: str) -> str:
    """Corrige erros comuns de OCR em títulos históricos/digitalizados antes da formatação."""
    t = re.sub(r"\b(?:CHABACTER|CRARACTER)\b", "CHARACTER", text, flags=re.I)
    t = re.sub(r"\bJ3ETHOR\b", "BETHOR", t, flags=re.I)
    t = re.sub(r"\bPRALEG\b", "PHALEG", t, flags=re.I)
    t = re.sub(r"\bSA\s+TURN\b", "SATURN", t, flags=re.I)
    t = re.sub(r"\bSymbois\.?\s+Circles\b", "Symbolic Circles", t, flags=re.I)
    t = re.sub(r"\bAro\s+Exorcisms\s+of\s+Tree\s+Band\b", "And Exorcisms of Three Bands", t, flags=re.I)
    t = re.sub(r"\bSpirits\.\s+Messengers\.", "Spirits, Messengers,", t, flags=re.I)
    return t


def _format_all_caps_title(raw_title: str) -> str:
    """Se o título estiver majoritariamente ou inteiramente em CAIXA ALTA, formata de modo legível preservando siglas."""
    cleaned = _clean_heading_ocr_typos(re.sub(r"\s+", " ", raw_title).strip())
    if len(cleaned) <= 5:
        return cleaned
    alpha_chars = [c for c in cleaned if c.isalpha()]
    upper_ratio = (
        sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
        if alpha_chars
        else 0.0
    )
    small_words = {
        "of", "the", "and", "in", "on", "for", "to", "with", "by", "at", "from",
        "de", "da", "do", "das", "dos", "e", "em", "na", "no", "nas", "nos", "para", "com", "a", "o",
        "la", "el", "los", "las", "del", "y", "en",
    }
    acronyms = {"RPDC", "DPRK", "EUA", "URSS", "ONU", "UNESCO"}
    if not cleaned.isupper() and upper_ratio < 0.72:
        # Mesmo em títulos mistos, normaliza palavras soltas em CAIXA ALTA longas (>=4 letras)
        words_mixed = cleaned.split()
        norm_mixed: List[str] = []
        for idx_w, w in enumerate(words_mixed):
            w_strip = w.strip(".,:;!?”\"'()")
            if (
                len(w_strip) >= 4
                and w_strip.isalpha()
                and w_strip.isupper()
                and w_strip not in acronyms
            ):
                prefix_p = "(" if w.startswith("(") else ""
                suffix_p = w[len(prefix_p) + len(w_strip):]
                norm_mixed.append(f"{prefix_p}{w_strip[0]}{w_strip[1:].lower()}{suffix_p}")
            elif idx_w > 0 and w_strip.lower() in small_words and not words_mixed[idx_w - 1].endswith((":", "—", "-")):
                norm_mixed.append(w.lower())
            else:
                norm_mixed.append(w)
        return " ".join(norm_mixed)
    words = cleaned.split()
    out: List[str] = []
    for i, w in enumerate(words):
        w_clean = w.strip(".,:;()[]\"'“”")
        if w_clean in acronyms:
            out.append(w)
        elif i > 0 and w.lower() in small_words:
            out.append(w.lower())
        else:
            # Trata apóstrofos como PEOPLE’S -> People’s
            parts = re.split(r"([’'\-])", w)
            formatted_parts = [
                p.capitalize() if idx == 0 or parts[idx - 1] == "-" else p.lower()
                for idx, p in enumerate(parts)
            ]
            out.append("".join(formatted_parts))
    return " ".join(out)


def _guess_book_metadata(doc: pymupdf.Document, pdf_path: str) -> Tuple[str, str]:
    meta = doc.metadata or {}
    raw_meta_title = normalize_typography(meta.get("title") or "").strip()
    author = normalize_typography(meta.get("author") or "").strip()

    title = raw_meta_title
    if (
        not title
        or len(title) < 3
        or _JUNK_META_TITLE_RE.search(title)
        or re.search(r"[\u3000-\u9fff\uac00-\ud7af]", title)
    ):
        title = ""

    if author and (
        len(author) < 2
        or author.lower()
        in (
            "admin",
            "administrator",
            "administrador",
            "user",
            "usuario",
            "usuário",
            "owner",
            "proprietário",
            "pc",
            "microsoft",
            "unknown",
        )
    ):
        author = ""

    # Tenta primeiro verificar ficha de publicação/copyright na página 2 (ex: "Towards a New Socialism? was published in 1993")
    if not title and len(doc) >= 2:
        p2_text = normalize_typography(doc[1].get_text("text"))
        m = re.search(r"([A-Z][A-Za-z0-9 ,:;\-’'?]+?)\s+was published in\s+\d{4}", p2_text)
        if m:
            title = m.group(1).strip(" ?")
        m_auth = re.search(r"copyright\s+([A-Z][A-Za-z. ,]+?)\.", p2_text)
        if m_auth and not author:
            author = m_auth.group(1).strip()

    # Tenta extrair o título e autor reais das páginas de capa/rosto (Páginas 1 e 2)
    if len(doc) >= 1:
        cover_lines: List[Tuple[int, float, float, str]] = []  # (page_idx, y0, size, text)
        for p_idx in range(min(2, len(doc))):
            d = doc[p_idx].get_text("dict")
            for b in d.get("blocks", []):
                if b.get("type") != 0:
                    continue
                for l in b.get("lines", []):
                    lt = normalize_typography(
                        "".join(s.get("text", "") for s in l.get("spans", []))
                    ).strip()
                    if not lt or _COVER_BOILERPLATE_RE.search(lt):
                        continue
                    sz = max((float(s.get("size", 0)) for s in l.get("spans", [])), default=0.0)
                    y0 = float(l["bbox"][1])
                    # Ignora running header pequeno no topo extremo da página
                    if y0 < 25.0 and sz < 13.0:
                        continue
                    cover_lines.append((p_idx, y0, sz, lt))

        p1_lines = [x for x in cover_lines if x[0] == 0]
        target_lines = p1_lines if p1_lines else cover_lines

        # Caso 1: Série "UNDERSTANDING KOREA"
        if not title:
            uk_texts = [x[3] for x in target_lines]
            joined_uk = " ".join(uk_texts)
            m_uk = re.search(
                r"UNDERSTANDING\s+KOREA\s+(\d+)\s+([A-Z &,\-]+)",
                joined_uk,
                re.I,
            )
            if m_uk:
                vol_num = m_uk.group(1).strip()
                vol_theme = _format_all_caps_title(m_uk.group(2).strip())
                title = f"Understanding Korea {vol_num}: {vol_theme}"
                if not author:
                    author = "Foreign Languages Publishing House"

        # Caso 2: Nome do autor no topo em destaque seguido pelo título do livro (ex: KIM IL SUNG + THE PUBLIC HEALTH LAW...)
        if not title and target_lines:
            known_authors = ("KIM IL SUNG", "KIM JONG IL", "KIM JONG UN")
            first_line_txt = target_lines[0][3].upper()
            if first_line_txt in known_authors and len(target_lines) >= 2:
                if not author:
                    author = _format_all_caps_title(target_lines[0][3])
                rem = [x for x in target_lines[1:] if x[2] >= 14.0]
                if rem:
                    max_rem_sz = max(x[2] for x in rem)
                    title_parts = [x[3] for x in rem if x[2] >= max_rem_sz - 3.0]
                    title = _format_all_caps_title(" ".join(title_parts))

        # Caso 3: Linhas com maior fonte na Página 1 (ou caso o título do metadado esteja truncado, ex: "THE SECRET GRIMOIRE" vs "THE SECRET GRIMOIRE OF TURIEL")
        if target_lines:
            prominent = [x for x in target_lines if x[2] >= 16.0 and not re.fullmatch(r"\d+", x[3])]
            if prominent:
                max_sz = max(x[2] for x in prominent)
                raw_candidates = [
                    txt for _p, _y, sz, txt in prominent if sz >= max_sz - 4.5
                ]
                # Remove fragmentos que são substrings de outra linha candidata do mesmo tamanho na capa (ex: "COMERCIO EXTE" vs "COMERCIO EXTERIOR")
                title_parts = []
                for txt in raw_candidates:
                    if len(txt) >= 4 and any(
                        txt.lower() != other.lower() and txt.lower() in other.lower()
                        for other in raw_candidates
                    ):
                        continue
                    if not title_parts or txt.lower() != title_parts[-1].lower():
                        title_parts.append(txt)
                candidate = _format_all_caps_title(" ".join(title_parts))
                if 4 <= len(candidate) <= 150:
                    if not title or (
                        title.isupper()
                        and title.lower() in candidate.lower()
                        and len(candidate) > len(title)
                    ):
                        title = _format_all_caps_title(candidate)
                    elif title.isupper():
                        title = _format_all_caps_title(title)

    if not title:
        base = os.path.splitext(os.path.basename(pdf_path))[0]
        title = base.replace("_", " ").replace("-", " ").title()

    if not author:
        author = "Autor Desconhecido"

    return title, author


def _estimate_body_font_size(doc: pymupdf.Document) -> float:
    """Estima o tamanho da fonte principal (corpo do texto) analisando uma amostra de páginas."""
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
    if not font_sizes:
        return 10.0
    return font_sizes.most_common(1)[0][0]


_CHAPTER_MARKER_RE = re.compile(
    r"^(?:\[\d+\]\s*)?(Chapter|Capítulo|Capitulo|Part|Parte|Book|Livro|Section|Seção|Secção)\s+"
    r"((?:the\s+)?(?:[0-9]+|[IVXLCDM]+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|"
    r"First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|"
    r"Um|Dois|Três|Quatro|Cinco|Seis|Sete|Oito|Nove|Dez|"
    r"Primeiro|Primeira|Segundo|Segunda|Terceiro|Terceira))\b[:.\-–—\s]*(.*)$",
    re.I,
)

_STANDALONE_CHAPTER_TITLES_RE = re.compile(
    r"^(?:\[\d+\]\s*)?(Preâmbulo|Preambulo|Preamble|Contents|Table of Contents|Sumário|Sumario|"
    r"Índice|Indice|I\s+n\s+d\s+i\s+c\s+e|Introduction|Introdução|Preface|Prefácio|"
    r"Foreword|Apresentação|Apresentação da coleção|Lista de siglas e abreviaturas|"
    r"Prologue|Prólogo|Epilogue|Epílogo|Conclusion|Conclusão|"
    r"Afterword|Posfácio|Appendix|Apêndice|Bibliography|Bibliografia|References|Referências|"
    r"Notes|Notas|Glossary|Glossário|Index|Acknowledgements|Acknowledgments|Agradecimentos)[:.\-–—]*$",
    re.I,
)

_ARTICLE_START_RE = re.compile(
    r"^(Art(?:icle|igo|ículo|\.)\s*[0-9]+[º°.]?)\b",
    re.I,
)

_STANDALONE_ARTICLE_RE = re.compile(
    r"^Art(?:icle|igo|ículo|\.)\s*[0-9]+[º°.]?$",
    re.I,
)

_NUMBERED_ITEM_START_RE = re.compile(
    r"^(\d{1,3}\.\s+\S+|\(\d{1,3}\)\s+\S+)",
)

_TOC_DOT_LEADER_RE = re.compile(r"\.{3,}\s*\d{1,4}\s*$")


@dataclass
class _LogicalUnit:
    page_num: int
    bbox: Tuple[float, float, float, float]
    raw_text: str
    text: str
    max_font_size: float
    is_bold: bool
    all_bold: bool
    fonts: List[str]


def _span_is_bold(span: dict) -> bool:
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


def _extract_page_logical_units(
    page: pymupdf.Page,
    page_num: int,
    body_font_size: float,
    opts: EnhancementOptions,
) -> Tuple[List[_LogicalUnit], List[ParagraphItem]]:
    """
    Extrai e divide os blocos de uma página do PDF em unidades lógicas limpas:
    1. Une palavras quebradas na mesma coordenada Y horizontal (justificação de PDF).
    2. Remove duplicatas de texto sobreposto (efeito sombra em títulos de revistas).
    3. Divide blocos onde o PyMuPDF agrupou títulos de capítulos, Artigos ou subtítulos
       em negrito junto com parágrafos normais.
    4. Filtra cabeçalhos/rodapés repetitivos e separa notas de rodapé da base da página.
    """
    page_height = float(page.rect.height)
    page_dict = page.get_text("dict")
    units: List[_LogicalUnit] = []
    footnotes: List[ParagraphItem] = []

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue

        raw_lines = block.get("lines", [])
        if not raw_lines:
            continue

        # Passo 1: Mesclar spans de linhas que estão na mesma linha horizontal (mesmo Y0 ± 3pt)
        merged_horiz_lines: List[dict] = []
        for l in raw_lines:
            l_bbox = tuple(l.get("bbox", (0.0, 0.0, 0.0, 0.0)))
            spans = l.get("spans", [])
            line_str = strip_control_chars("".join(s.get("text", "") for s in spans)).strip()

            if (
                merged_horiz_lines
                and line_str
                and merged_horiz_lines[-1]["line_str"]
                and abs(l_bbox[1] - merged_horiz_lines[-1]["bbox"][1]) <= 3.0
            ):
                prev_entry = merged_horiz_lines[-1]
                # Ignora sombra idêntica na mesma linha
                if line_str == prev_entry["line_str"] and abs(l_bbox[0] - prev_entry["bbox"][0]) <= 5.0:
                    continue
                prev_entry["spans"].extend([{"text": " ", "size": prev_entry["max_sz"], "font": "", "flags": 0}] + spans)
                prev_entry["line_str"] = (prev_entry["line_str"] + " " + line_str).strip()
                prev_entry["bbox"] = (
                    min(prev_entry["bbox"][0], l_bbox[0]),
                    min(prev_entry["bbox"][1], l_bbox[1]),
                    max(prev_entry["bbox"][2], l_bbox[2]),
                    max(prev_entry["bbox"][3], l_bbox[3]),
                )
                continue

            # Ignora linha de sombra idêntica imediatamente abaixo (ex: título duplicado em revista)
            if (
                merged_horiz_lines
                and line_str
                and line_str == merged_horiz_lines[-1]["line_str"]
                and abs(l_bbox[1] - merged_horiz_lines[-1]["bbox"][1]) <= 6.0
            ):
                continue

            non_empty_spans = [
                (strip_control_chars(s.get("text", "")).strip(), float(s.get("size", body_font_size)), s)
                for s in spans
                if strip_control_chars(s.get("text", "")).strip()
            ]
            max_sz = max((sz for _t, sz, _s in non_empty_spans), default=0.0)
            # Evita que uma letra capitular inline (ex: 'T' 30pt + 'HE S.S. Umvoti...' 18pt) infle o tamanho da linha inteira
            if len(non_empty_spans) >= 2:
                first_txt, first_sz, _ = non_empty_spans[0]
                rest_len = sum(len(t) for t, _sz, _s in non_empty_spans[1:])
                rest_max_sz = max(sz for _t, sz, _s in non_empty_spans[1:])
                if (
                    len(first_txt) <= 2
                    and first_sz >= body_font_size + 4.0
                    and rest_len >= 10
                    and rest_max_sz <= body_font_size + 1.5
                ):
                    max_sz = rest_max_sz

            merged_horiz_lines.append(
                {
                    "bbox": l_bbox,
                    "spans": list(spans),
                    "line_str": line_str,
                    "max_sz": max_sz or body_font_size,
                }
            )

        # Passo 1.5: Separar cabeçalhos inline seguidos de ':—' na mesma linha (ex: "First Morning Prayer :— Almighty...")
        expanded_horiz_lines: List[dict] = []
        inline_hdr_re = re.compile(
            r"^([A-ZÀ-Ú][^\n:]{2,70}?)\s*(?::\.?\s*[—–\-]+|:\s*I\b|:\s+—)\s*(.+)$"
        )
        for hl in merged_horiz_lines:
            l_str = hl["line_str"]
            m_in = inline_hdr_re.match(l_str)
            if m_in:
                hdr_part = m_in.group(1).strip()
                body_part = m_in.group(2).strip()
                alpha_sp = [
                    s for s in hl["spans"] if strip_control_chars(s.get("text", "")).strip()
                ]
                first_sp = alpha_sp[0] if alpha_sp else {}
                first_is_styled = _span_is_bold(first_sp) or (
                    bool(int(first_sp.get("flags", 0)) & 2)
                    or "ital" in (first_sp.get("font") or "").lower()
                )
                if first_is_styled and len(hdr_part) >= 3 and len(body_part) >= 5:
                    x0, y0, x1, y1 = hl["bbox"]
                    mid_y = y0 + (y1 - y0) * 0.45
                    hdr_span = {
                        "text": hdr_part,
                        "size": hl["max_sz"],
                        "font": (first_sp.get("font") or "Bold") + ",Bold",
                        "flags": int(first_sp.get("flags", 0)) | 16,
                    }
                    body_span = {
                        "text": body_part,
                        "size": body_font_size,
                        "font": "Regular",
                        "flags": 0,
                    }
                    expanded_horiz_lines.append(
                        {
                            "bbox": (x0, y0, x1, mid_y),
                            "spans": [hdr_span],
                            "line_str": hdr_part,
                            "max_sz": hl["max_sz"],
                        }
                    )
                    expanded_horiz_lines.append(
                        {
                            "bbox": (x0, mid_y + 1.0, x1, y1),
                            "spans": [body_span],
                            "line_str": body_part,
                            "max_sz": body_font_size,
                        }
                    )
                    continue

            # Limpa sufixos de pontuação ritualística em títulos isolados (ex: "Consecration of the Sword :—", "... TO ~")
            cleaned_hdr_str = re.sub(
                r"\s*(?:,\s*saying\s*)?:\.?\s*[—–\-]+\s*$|\s+TO\s*~\s*$",
                "",
                l_str,
                flags=re.I,
            ).strip()
            if cleaned_hdr_str and cleaned_hdr_str != l_str:
                hl = dict(hl)
                hl["line_str"] = cleaned_hdr_str
            expanded_horiz_lines.append(hl)

        merged_horiz_lines = expanded_horiz_lines

        # Passo 2: Agrupar as linhas horizontais em unidades lógicas (_LogicalUnit)
        curr_lines_str: List[str] = []
        curr_bbox: Optional[Tuple[float, float, float, float]] = None
        curr_max_sz: float = 0.0
        curr_fonts: List[str] = []
        curr_any_bold: bool = False
        curr_all_bold: bool = True
        prev_y1: Optional[float] = None
        prev_h: float = 12.0

        def _flush_unit() -> None:
            nonlocal curr_lines_str, curr_bbox, curr_max_sz, curr_fonts, curr_any_bold, curr_all_bold, prev_y1
            if not curr_lines_str or curr_bbox is None:
                curr_lines_str = []
                curr_bbox = None
                curr_max_sz = 0.0
                curr_fonts = []
                curr_any_bold = False
                curr_all_bold = True
                prev_y1 = None
                return

            raw_u = "\n".join(curr_lines_str).strip()
            u_bbox = curr_bbox
            u_max_sz = curr_max_sz
            u_fonts = list(curr_fonts)
            u_any_bold = curr_any_bold
            u_all_bold = curr_all_bold

            curr_lines_str = []
            curr_bbox = None
            curr_max_sz = 0.0
            curr_fonts = []
            curr_any_bold = False
            curr_all_bold = True
            prev_y1 = None

            if not raw_u:
                return

            if opts.remove_headers_footers and _is_running_header_or_footer(
                u_bbox,
                raw_u,
                page_height,
                max_font_size=u_max_sz,
                body_font_size=body_font_size,
            ):
                return

            if opts.footnote_mode in ("move_end", "remove") and _is_footnote_block(
                u_bbox, raw_u, u_max_sz, body_font_size, page_height
            ):
                if opts.footnote_mode == "move_end":
                    fn_cleaned = reflow_lines_in_block(
                        raw_u,
                        do_normalize=opts.normalize_chars,
                        do_reflow=opts.reflow_sentences,
                    )
                    if fn_cleaned:
                        footnotes.append(
                            ParagraphItem(
                                text=f"[Nota pág. {page_num}] {fn_cleaned}",
                                kind="footnote",
                                page_number=page_num,
                            )
                        )
                return

            reflowed = reflow_lines_in_block(
                raw_u,
                do_normalize=opts.normalize_chars,
                do_reflow=opts.reflow_sentences,
            )
            if not reflowed:
                return

            units.append(
                _LogicalUnit(
                    page_num=page_num,
                    bbox=u_bbox,
                    raw_text=raw_u,
                    text=reflowed,
                    max_font_size=u_max_sz,
                    is_bold=u_any_bold,
                    all_bold=u_all_bold,
                    fonts=u_fonts,
                )
            )

        for hl in merged_horiz_lines:
            l_str = hl["line_str"]
            if not l_str:
                # Linha em branco explícita dentro do bloco do PDF separa parágrafos/títulos!
                _flush_unit()
                continue

            l_bbox = hl["bbox"]
            l_max_sz = hl["max_sz"]
            l_spans = hl["spans"]

            alpha_spans = [
                s for s in l_spans if strip_control_chars(s.get("text", "")).strip()
            ]
            l_any_bold = any(_span_is_bold(s) for s in alpha_spans)
            l_all_bold = bool(alpha_spans) and all(_span_is_bold(s) for s in alpha_spans)
            l_fonts = [s["font"] for s in alpha_spans if s.get("font")]

            if curr_lines_str:
                should_split = False
                curr_joined = " ".join(curr_lines_str).strip()

                # 1. Espaçamento vertical grande entre linhas
                if prev_y1 is not None:
                    v_gap = l_bbox[1] - prev_y1
                    if v_gap > max(7.5, prev_h * 0.65):
                        # Permite manter juntas linhas de um mesmo título gigante de capa/revista
                        if not (curr_max_sz >= body_font_size + 5.0 and abs(l_max_sz - curr_max_sz) <= 2.5):
                            should_split = True

                # 2. Linha atual inicia um Capítulo / Parte / Seção isolada ou linha de Sumário com pontilhado
                if _CHAPTER_MARKER_RE.match(l_str) or _STANDALONE_CHAPTER_TITLES_RE.match(l_str):
                    should_split = True
                if _TOC_DOT_LEADER_RE.search(curr_lines_str[-1]) or _TOC_DOT_LEADER_RE.search(l_str):
                    should_split = True

                # 3. Unidade atual já é um marcador de capítulo e a nova linha é um Artigo ou texto normal
                if _CHAPTER_MARKER_RE.match(curr_joined) or _STANDALONE_CHAPTER_TITLES_RE.match(curr_joined):
                    if _ARTICLE_START_RE.match(l_str) or not (
                        l_str.isupper() or l_all_bold or l_max_sz >= body_font_size + 1.5
                    ):
                        should_split = True

                # 4. Início de Artigo de lei/constituição ("Article 1.", "Artigo 1")
                if _ARTICLE_START_RE.match(l_str):
                    should_split = True

                # 5. Unidade atual é um cabeçalho isolado "Artigo N"
                if _STANDALONE_ARTICLE_RE.match(curr_joined):
                    should_split = True

                # 6. Mudança brusca de tamanho de fonte
                if abs(l_max_sz - curr_max_sz) >= 1.5:
                    should_split = True

                # 7. Item numerado ("1. ...", "2. ...")
                if _NUMBERED_ITEM_START_RE.match(l_str):
                    if (
                        l_all_bold
                        or curr_all_bold != l_all_bold
                        or curr_lines_str[-1].endswith((".", ":", ";", "!", "?"))
                    ):
                        should_split = True

                # 8. Transição entre título em negrito (ex: "1. Location" ou "Invocation for Monday (MOON)") e corpo normal
                if curr_all_bold != l_all_bold or curr_any_bold != l_any_bold:
                    if (
                        (curr_all_bold or curr_any_bold)
                        and not l_any_bold
                        and len(curr_joined) <= 130
                        and (not curr_joined.endswith(".") or curr_joined.isupper())
                    ):
                        should_split = True
                    elif l_all_bold and (
                        _NUMBERED_ITEM_START_RE.match(l_str) or l_str.isupper()
                    ):
                        should_split = True

                if should_split:
                    _flush_unit()

            curr_lines_str.append(l_str)
            if curr_bbox is None:
                curr_bbox = l_bbox
                curr_all_bold = l_all_bold
            else:
                curr_bbox = (
                    min(curr_bbox[0], l_bbox[0]),
                    min(curr_bbox[1], l_bbox[1]),
                    max(curr_bbox[2], l_bbox[2]),
                    max(curr_bbox[3], l_bbox[3]),
                )
                curr_all_bold = curr_all_bold and l_all_bold

            if l_max_sz > curr_max_sz:
                curr_max_sz = l_max_sz
            curr_any_bold = curr_any_bold or l_any_bold
            curr_fonts.extend(l_fonts)
            prev_y1 = l_bbox[3]
            prev_h = max(8.0, l_bbox[3] - l_bbox[1])

        _flush_unit()

    # Ordena as unidades da página de cima para baixo (Y0 crescente, depois X0)
    # Isso garante que títulos de capítulos no topo da página venham SEMPRE antes de capitulares (drop-caps)
    units.sort(key=lambda u: (round(u.bbox[1], 1), round(u.bbox[0], 1)))

    # Reanexa letras capitulares (Drop-Caps, ex: 'N' + 'os primeiros passos' -> 'Nos primeiros passos',
    # 'O' + 'que é a cidade?' -> 'O que é a cidade?', '“N' + 'ós nas aldeias' -> '“Nós nas aldeias')
    standalone_one_letter_words = {"A", "O", "E", "À", "É", "I", "Y", "U"}
    complete_next_words = {
        "que", "qual", "quais", "quem", "quando", "onde", "como", "por", "para",
        "pelo", "pela", "pelos", "pelas", "em", "no", "na", "nos", "nas", "num",
        "numa", "de", "do", "da", "dos", "das", "se", "não", "já", "mais", "menos",
        "muito", "muita", "todo", "toda", "todos", "todas", "outro", "outra",
        "mesmo", "mesma", "um", "uma",
    }
    merged_units: List[_LogicalUnit] = []
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
            # Verifica se o próximo bloco é o parágrafo que acompanha a capitular na mesma faixa vertical
            if (
                u_next.max_font_size <= body_font_size + 2.5
                and abs(u_next.bbox[1] - u_curr.bbox[1]) <= u_curr.max_font_size * 0.9
            ):
                next_txt = u_next.text.lstrip()
                first_word = re.split(r"[\s,.;:!?]+", next_txt)[0].lower() if next_txt else ""
                if next_txt and next_txt[0].isupper():
                    joined_txt = f"{curr_txt} {next_txt}"
                elif (
                    core_alpha.upper() in standalone_one_letter_words
                    and first_word in complete_next_words
                ):
                    joined_txt = f"{curr_txt} {next_txt}"
                else:
                    joined_txt = f"{curr_txt}{next_txt}"

                u_next.text = joined_txt
                u_next.raw_text = f"{curr_txt}{u_next.raw_text}"
                u_next.bbox = (
                    min(u_curr.bbox[0], u_next.bbox[0]),
                    min(u_curr.bbox[1], u_next.bbox[1]),
                    max(u_curr.bbox[2], u_next.bbox[2]),
                    max(u_curr.bbox[3], u_next.bbox[3]),
                )
                merged_units.append(u_next)
                idx_u += 2
                continue
        merged_units.append(u_curr)
        idx_u += 1

    return merged_units, footnotes


def _detect_printed_toc_pages(
    pages_units: Dict[int, List[_LogicalUnit]],
    total_pages: int,
) -> Tuple[Set[int], List[Tuple[str, int]]]:
    """
    Identifica páginas de Sumário impresso ('Contents', 'Sumário', 'Índice', 'I n d i c e')
    e extrai suas entradas (título, página impressa) caso seja necessário usá-las como referência.
    """
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

        has_toc_header = any(toc_header_re.match(u.text) for u in p_units[:4])
        dot_leader_count = sum(1 for u in p_units if _TOC_DOT_LEADER_RE.search(u.text))
        bracket_num_count = sum(
            1 for u in p_units if re.search(r"\[\d{1,4}\]\s*$", u.text)
        )

        is_toc_pg = False
        if has_toc_header and (dot_leader_count >= 1 or bracket_num_count >= 2 or len(p_units) >= 4):
            is_toc_pg = True
        elif dot_leader_count >= 3:
            is_toc_pg = True
        elif (pno - 1) in toc_pages and dot_leader_count >= 1 and dot_leader_count >= len(p_units) * 0.5:
            is_toc_pg = True

        if is_toc_pg:
            toc_pages.add(pno)
            for u in p_units:
                m_dot = re.match(
                    r"^(.+?)(?:\s*\.{2,}\s*|\s{3,})(\d{1,4})$",
                    u.text.strip(),
                )
                if m_dot:
                    t_clean = m_dot.group(1).strip(" .")
                    pg_num = int(m_dot.group(2))
                    if len(t_clean) >= 2:
                        printed_entries.append((t_clean, pg_num))

    return toc_pages, printed_entries


def _discover_chapters_from_units(
    body_units: List[_LogicalUnit],
    body_font_size: float,
    printed_entries: List[Tuple[str, int]],
    toc_pages: Set[int],
    p_start: int,
    p_end: int,
) -> Tuple[List[Tuple[str, int, int]], Set[int], str]:
    """
    Descobre onde cada capítulo começa dentro da lista de unidades lógicas `body_units`.
    Retorna:
      - Lista de tuplas `(chapter_title, start_unit_idx, end_unit_idx_exclusive)`
      - Conjunto de índices de unidades que foram consumidas como parte do título do capítulo
      - Nome do método de descoberta utilizado
    """
    n_units = len(body_units)
    if n_units == 0:
        return [], set(), "single_section"

    # =========================================================================
    # CAMADA 1: Marcadores explícitos de Capítulo / Parte / Preâmbulo / Introdução
    # (Funciona inclusive no meio da página ou com múltiplos capítulos na mesma página!)
    # =========================================================================
    explicit_starts: List[Tuple[str, int]] = []
    consumed_heading_indices: Set[int] = set()

    i = 0
    while i < n_units:
        u = body_units[i]
        txt_clean = _strip_page_brackets(u.text)

        if not _TOC_DOT_LEADER_RE.search(txt_clean):
            m_chap = _CHAPTER_MARKER_RE.match(txt_clean)
            if (
                m_chap
                and len(txt_clean) <= 120
                and not txt_clean.endswith((",", ";"))
                and (not txt_clean.endswith(".") or txt_clean.isupper() or u.is_bold)
            ):
                prefix_word = m_chap.group(1)
                chap_num = m_chap.group(2)
                rest_title = m_chap.group(3).strip().rstrip(".")

                # Evita confundir frases normais do corpo (ex: "Part 1 consists of three scenes...") com título de capítulo
                is_valid_chap_heading = (
                    (not rest_title or rest_title[0].isupper() or rest_title[0].isdigit())
                    and (
                        not rest_title
                        or txt_clean.isupper()
                        or u.is_bold
                        or u.all_bold
                        or u.max_font_size >= body_font_size + 1.2
                    )
                )
                if is_valid_chap_heading:
                    consumed_heading_indices.add(i)
                    extra_parts: List[str] = [rest_title] if rest_title else []

                    # Olha as próximas 1 a 3 unidades na mesma página para capturar o subtítulo do capítulo
                    # (ex: "CHAPTER II" + "THE SYSTEM OF COMPLETE AND" + "UNIVERSAL FREE MEDICAL SERVICE")
                    j = i + 1
                    while j < n_units and j <= i + 3 and body_units[j].page_num == u.page_num:
                        nxt = body_units[j]
                        nxt_txt = _strip_page_brackets(nxt.text)
                        if (
                            _CHAPTER_MARKER_RE.match(nxt_txt)
                            or _STANDALONE_CHAPTER_TITLES_RE.match(nxt_txt)
                            or _ARTICLE_START_RE.match(nxt_txt)
                            or _NUMBERED_ITEM_START_RE.match(nxt_txt)
                            or _TOC_DOT_LEADER_RE.search(nxt_txt)
                        ):
                            break
                        is_subtitle_style = (
                            nxt_txt.isupper()
                            or nxt.all_bold
                            or nxt.max_font_size >= body_font_size + 1.5
                        )
                        if (
                            is_subtitle_style
                            and len(nxt_txt) <= 95
                            and not nxt_txt.endswith((".", ";", "!"))
                        ):
                            extra_parts.append(nxt_txt)
                            consumed_heading_indices.add(j)
                            j += 1
                        else:
                            break

                    subtitle_str = _format_all_caps_title(" ".join(extra_parts).strip())
                    prefix_formatted = _format_all_caps_title(f"{prefix_word} {chap_num}")
                    # Mantém algarismos romanos em maiúsculas
                    if re.fullmatch(r"[IVXLCDM]+", chap_num, re.I):
                        prefix_formatted = f"{prefix_word.capitalize()} {chap_num.upper()}"

                    full_title = (
                        f"{prefix_formatted}: {subtitle_str}"
                        if subtitle_str
                        else prefix_formatted
                    )
                    explicit_starts.append((full_title, i))
                    i = j
                    continue

            if _STANDALONE_CHAPTER_TITLES_RE.match(txt_clean):
                is_prominent = (
                    u.is_bold
                    or u.all_bold
                    or u.max_font_size >= body_font_size + 1.2
                    or txt_clean.isupper()
                )
                if is_prominent:
                    consumed_heading_indices.add(i)
                    clean_st_title = txt_clean.rstrip(".:-–— ")
                    explicit_starts.append((_format_all_caps_title(clean_st_title), i))
                    i += 1
                    continue

        i += 1

    # Remove repetições consecutivas idênticas (running header que escapou)
    dedup_explicit: List[Tuple[str, int]] = []
    for title, u_idx in explicit_starts:
        if dedup_explicit and dedup_explicit[-1][0].lower() == title.lower():
            continue
        dedup_explicit.append((title, u_idx))

    first_explicit_pg = (
        body_units[dedup_explicit[0][1]].page_num if dedup_explicit else p_end + 1
    )
    explicit_starts_early_enough = first_explicit_pg <= p_start + max(
        8, int((p_end - p_start) * 0.40)
    )

    explicit_pages = [body_units[u_idx].page_num for _t, u_idx in dedup_explicit] + [p_end]
    max_explicit_gap = (
        max(
            (explicit_pages[idx + 1] - explicit_pages[idx] for idx in range(len(explicit_pages) - 1)),
            default=0,
        )
        if dedup_explicit
        else p_end - p_start
    )

    # Retorna imediatamente pela Camada 1 se houver capítulos regulares cobrindo o livro sem hiatos gigantes
    if (
        explicit_starts_early_enough
        and (
            len(dedup_explicit) >= 5
            or (len(dedup_explicit) >= 2 and max_explicit_gap <= 8)
            or (len(dedup_explicit) == 1 and (p_end - p_start) <= 15)
        )
    ):
        spans: List[Tuple[str, int, int]] = []
        if dedup_explicit[0][1] > 0:
            spans.append(("Informações Iniciais", 0, dedup_explicit[0][1]))
        for idx_s, (ch_title, start_u) in enumerate(dedup_explicit):
            end_u = dedup_explicit[idx_s + 1][1] if idx_s + 1 < len(dedup_explicit) else n_units
            if start_u < end_u:
                spans.append((ch_title, start_u, end_u))
        return spans, consumed_heading_indices, "heuristic_typography"

    # =========================================================================
    # CAMADA 2: Tópicos / Seções Numeradas em Negrito ("1. Location", "2. Area"...)
    # Ideal para livros enciclopédicos / guias como a série "Understanding Korea"
    # =========================================================================
    numbered_candidates: List[Tuple[int, str, int]] = []  # (topic_num, title, unit_idx)
    numbered_re = re.compile(r"^(\d{1,3})\.\s+([A-ZÀ-Ú“\"‘'0-9].*)$")

    for idx_u, u in enumerate(body_units):
        if u.page_num <= 2 and toc_pages:
            continue
        if (u.all_bold or (u.is_bold and u.max_font_size >= body_font_size + 0.5)) and len(u.text) <= 130:
            if u.text.endswith((".", ";", "!", "?")):
                continue
            m_num = numbered_re.match(u.text.strip())
            if m_num:
                t_num = int(m_num.group(1))
                numbered_candidates.append((t_num, u.text.strip(), idx_u))

    # Filtra sequência monotonicamente crescente começando perto de 1
    seq_numbered: List[Tuple[int, str, int]] = []
    for t_num, t_title, u_idx in numbered_candidates:
        if not seq_numbered:
            if 1 <= t_num <= 3:
                seq_numbered.append((t_num, t_title, u_idx))
        else:
            prev_num = seq_numbered[-1][0]
            if 1 <= (t_num - prev_num) <= 5:
                seq_numbered.append((t_num, t_title, u_idx))

    if len(seq_numbered) >= 4:
        consumed_num: Set[int] = {u_idx for _n, _t, u_idx in seq_numbered}
        spans = []
        if seq_numbered[0][2] > 0:
            spans.append(("Informações Iniciais", 0, seq_numbered[0][2]))
        for idx_s, (_t_num, ch_title, start_u) in enumerate(seq_numbered):
            end_u = seq_numbered[idx_s + 1][2] if idx_s + 1 < len(seq_numbered) else n_units
            if start_u < end_u:
                spans.append((ch_title, start_u, end_u))
        return spans, consumed_num, "heuristic_typography"

    # =========================================================================
    # CAMADA 3: Títulos em Fonte Grande de Destaque ou Seções em Negrito
    # (Revistas, Grimórios e Livros sem numeração sequencial "Capítulo N")
    # =========================================================================
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
    # Frequência de textos curtos para não transformar sub-rótulos repetidos (ex: "Perfumes" 7x) em capítulos
    short_text_freq: Counter[str] = Counter(
        u.text.strip().lower().rstrip(".:")
        for u in body_units
        if len(u.text.strip()) <= 40
    )
    # Identifica páginas de catálogo publicitário no final do livro (ex: "Compre agora e leia")
    ad_pages: Set[int] = {
        u.page_num
        for u in body_units
        if re.search(r"compre\s+agora\s+e\s+leia", u.text, re.I)
    }

    k = 0
    while k < n_units:
        if k in consumed_heading_indices:
            k += 1
            continue
        u = body_units[k]
        u_txt = u.text.strip()
        u_key = u_txt.lower().rstrip(".:")

        is_large_display = (
            u.max_font_size >= body_font_size + 2.5
            and (
                not u_txt.endswith(".")
                or u_txt.isupper()
                or bool(re.match(r"^(CHARACTER|CHABACTER|CRARACTER)\b", u_txt, re.I))
            )
        )
        is_bold_section_heading = (
            (u.is_bold or bool(re.match(r"^(Form of a\b|Oration\b)", u_txt, re.I)))
            and (
                u.max_font_size >= body_font_size + 1.2
                or (
                    short_text_freq[u_key] <= 2
                    and not u_txt.endswith((".", ";", "!"))
                    and len(u_txt.split()) <= 16
                )
            )
        )

        if (
            u.page_num > 1
            and u.page_num not in ad_pages
            and (u.page_num - 1) not in ad_pages
            and (is_large_display or is_bold_section_heading)
            and 4 <= len(u_txt) <= 95
            and not noise_re.search(u_txt)
            and not caption_ignore_re.search(u_txt)
            and not re.fullmatch(r"\d+", u_txt)
        ):
            parts = [u_txt.rstrip(".:")]
            temp_consumed = {k}
            m_k = k + 1
            while (
                is_large_display
                and m_k < n_units
                and m_k <= k + 3
                and body_units[m_k].page_num == u.page_num
                and m_k not in consumed_heading_indices
            ):
                nxt = body_units[m_k]
                if (
                    nxt.max_font_size >= body_font_size + 2.5
                    and (
                        abs(nxt.max_font_size - u.max_font_size) <= 12.0
                        or (
                            u.max_font_size >= body_font_size + 8.0
                            and nxt.max_font_size >= body_font_size + 8.0
                        )
                    )
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
            combined = _format_all_caps_title(" ".join(parts).strip())
            # Se na página 2 for apenas folha de rosto ou se na ficha catalográfica final repetir o próprio título
            is_colophon_page = any(
                "©" in other_u.text or "Dados Internacionais de Catalogação" in other_u.text
                for other_u in body_units[max(0, k - 2) : min(n_units, m_k + 5)]
                if other_u.page_num == u.page_num
            )
            if len(combined) >= 4 and u.page_num > 2 and not is_colophon_page:
                consumed_display.update(temp_consumed)
                display_starts.append((combined, k))
            elif len(combined) >= 4 and u.page_num == 2 and (p_end - p_start) <= 40:
                # Em revistas curtas (ex: ~36 págs), a página 2 já pode ser o primeiro artigo
                consumed_display.update(temp_consumed)
                display_starts.append((combined, k))
            k = m_k
            continue
        k += 1

    # Combina marcadores explícitos da Camada 1 (ex: "Part I", "Introduction", "Part the Second")
    # com os cabeçalhos tipográficos descobertos na Camada 3
    combined_starts_map: Dict[int, str] = {}
    for ch_t, u_idx in dedup_explicit:
        combined_starts_map[u_idx] = ch_t
    for ch_t, u_idx in display_starts:
        if u_idx not in combined_starts_map:
            combined_starts_map[u_idx] = ch_t

    merged_display_starts: List[Tuple[str, int]] = [
        (combined_starts_map[idx_k], idx_k) for idx_k in sorted(combined_starts_map.keys())
    ]
    all_consumed = consumed_heading_indices | consumed_display

    # Se um marcador macro (ex: "Part I" ou "Part the Second") não possui unidades próprias
    # não-consumidas antes do próximo capítulo imediato, funde seu título como prefixo do capítulo seguinte
    consolidated_starts: List[Tuple[str, int]] = []
    idx_m = 0
    while idx_m < len(merged_display_starts):
        ch_t, start_u = merged_display_starts[idx_m]
        if idx_m + 1 < len(merged_display_starts):
            next_t, next_u = merged_display_starts[idx_m + 1]
            has_non_consumed = any(
                u_i not in all_consumed for u_i in range(start_u, next_u)
            )
            if not has_non_consumed:
                merged_display_starts[idx_m + 1] = (f"{ch_t} — {next_t}", start_u)
                idx_m += 1
                continue
        consolidated_starts.append((ch_t, start_u))
        idx_m += 1

    if len(consolidated_starts) >= 2:
        spans = []
        first_u_idx = consolidated_starts[0][1]
        if first_u_idx > 0:
            pre_units = body_units[:first_u_idx]
            pre_words = sum(len(u.text.split()) for u in pre_units)
            all_on_first_page = all(u.page_num == p_start for u in pre_units)
            if not (all_on_first_page and pre_words < 35):
                spans.append(("Informações Iniciais", 0, first_u_idx))
            else:
                all_consumed.update(range(0, first_u_idx))
        for idx_s, (ch_title, start_u) in enumerate(consolidated_starts):
            end_u = (
                consolidated_starts[idx_s + 1][1]
                if idx_s + 1 < len(consolidated_starts)
                else n_units
            )
            if start_u < end_u:
                spans.append((ch_title, start_u, end_u))
        return spans, all_consumed, "heuristic_typography"

    # =========================================================================
    # CAMADA 4: Mapeamento pelo Sumário Impresso (Printed TOC Parser)
    # =========================================================================
    if len(printed_entries) >= 3:
        last_toc_pg = max(toc_pages) if toc_pages else 1
        first_printed_pg = printed_entries[0][1]
        offset = max(0, last_toc_pg - first_printed_pg + 1)

        mapped_starts: List[Tuple[str, int]] = []
        for entry_title, entry_pg in printed_entries:
            target_pdf_pg = entry_pg + offset
            # Encontra a primeira unidade nessa página (ou subsequente)
            found_idx = None
            for idx_u, u in enumerate(body_units):
                if u.page_num >= target_pdf_pg:
                    found_idx = idx_u
                    break
            if found_idx is not None:
                if not mapped_starts or found_idx > mapped_starts[-1][1]:
                    mapped_starts.append((entry_title, found_idx))

        if len(mapped_starts) >= 2:
            spans = []
            if mapped_starts[0][1] > 0:
                spans.append(("Informações Iniciais", 0, mapped_starts[0][1]))
            for idx_s, (ch_title, start_u) in enumerate(mapped_starts):
                end_u = mapped_starts[idx_s + 1][1] if idx_s + 1 < len(mapped_starts) else n_units
                if start_u < end_u:
                    spans.append((ch_title, start_u, end_u))
            return spans, set(), "printed_toc_parser"

    # =========================================================================
    # CAMADA 5: Divisão inteligente em partes de ~12 páginas
    # =========================================================================
    step = 12
    spans = []
    for part_idx, pg in enumerate(range(p_start, p_end + 1, step), start=1):
        c_end = min(p_end, pg + step - 1)
        u_indices = [
            idx_u for idx_u, u in enumerate(body_units) if pg <= u.page_num <= c_end
        ]
        if u_indices:
            spans.append(
                (f"Parte {part_idx} (Páginas {pg} a {c_end})", u_indices[0], u_indices[-1] + 1)
            )
    return spans, set(), "smart_page_chunks"


def _populate_chapter_items_from_units(
    chapter: Chapter,
    units_slice: List[_LogicalUnit],
    consumed_indices: Set[int],
    slice_offset: int,
    footnotes: List[ParagraphItem],
    body_font_size: float,
    opts: EnhancementOptions,
) -> None:
    """Converte uma fatia de `_LogicalUnit`s nos `ParagraphItem`s de um `Chapter`."""
    for rel_idx, u in enumerate(units_slice):
        abs_idx = slice_offset + rel_idx
        if abs_idx in consumed_indices:
            continue

        cleaned_para = u.text
        if not cleaned_para:
            continue

        heading_kind = _is_heading_candidate(
            cleaned_para,
            u.max_font_size,
            u.is_bold,
            u.fonts,
            body_font_size,
            chapter.title,
        )
        if heading_kind == "skip":
            continue
        if heading_kind == "h2":
            chapter.items.append(
                ParagraphItem(
                    text=_strip_page_brackets(cleaned_para),
                    kind="h2",
                    page_number=u.page_num,
                )
            )
            continue

        if re.match(r"^(\([0-9a-zA-Z]+\)|[0-9]+\.)\s+", cleaned_para):
            sub_items = re.split(r"(?=\s+\([0-9a-zA-Z]+\)\s+)", cleaned_para)
            for sub in sub_items:
                sub_clean = sub.strip()
                if sub_clean:
                    chapter.items.append(
                        ParagraphItem(
                            text=sub_clean,
                            kind="list_item",
                            page_number=u.page_num,
                        )
                    )
            continue

        # Se o item anterior era um sub-rótulo isolado de 1 palavra (ex: "Perfumes"), une-o ao parágrafo
        if (
            chapter.items
            and chapter.items[-1].kind == "h2"
            and len(chapter.items[-1].text.split()) == 1
            and chapter.items[-1].text.lower().rstrip(":") in ("perfumes", "perfume", "incense", "incenso")
        ):
            lbl = chapter.items[-1].text.rstrip(":")
            chapter.items[-1].kind = "p"
            chapter.items[-1].text = f"{lbl}: {cleaned_para}"
            continue

        # União de parágrafos cortados no meio da frase entre blocos ou páginas
        if (
            opts.reflow_sentences
            and chapter.items
            and chapter.items[-1].kind in ("p", "list_item")
            and _should_merge_paragraphs(chapter.items[-1].text, cleaned_para)
        ):
            chapter.items[-1].text = _merge_two_texts(
                chapter.items[-1].text, cleaned_para
            )
        else:
            chapter.items.append(
                ParagraphItem(text=cleaned_para, kind="p", page_number=u.page_num)
            )

    if footnotes:
        chapter.items.append(
            ParagraphItem(
                text="Notas do Capítulo",
                kind="h2",
                page_number=chapter.end_page,
            )
        )
        chapter.items.extend(footnotes)


def extract_pdf_book(
    pdf_path: str,
    options: Optional[EnhancementOptions] = None,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
) -> BookStructure:
    """
    Extrai um livro inteiro de um arquivo PDF aplicando as opções granulares de aprimoramento.
    """
    opts = options or EnhancementOptions()
    doc = pymupdf.open(pdf_path)
    total_pages = len(doc)
    book_title, book_author = _guess_book_metadata(doc, pdf_path)

    p_start = max(1, start_page or 1)
    p_end = min(total_pages, end_page or total_pages)
    body_font_size = _estimate_body_font_size(doc)

    # Extrai as unidades lógicas e notas de rodapé página a página
    pages_units: Dict[int, List[_LogicalUnit]] = {}
    pages_footnotes: Dict[int, List[ParagraphItem]] = {}
    for page_num in range(p_start, p_end + 1):
        u_list, fn_list = _extract_page_logical_units(
            doc[page_num - 1], page_num, body_font_size, opts
        )
        pages_units[page_num] = u_list
        pages_footnotes[page_num] = fn_list

    chapters: List[Chapter] = []
    discovery_method = "embedded_toc"

    if not opts.organize_toc:
        all_units = [u for p in range(p_start, p_end + 1) for u in pages_units.get(p, [])]
        all_fns = [fn for p in range(p_start, p_end + 1) for fn in pages_footnotes.get(p, [])]
        ch = Chapter(index=1, title=book_title, start_page=p_start, end_page=p_end)
        _populate_chapter_items_from_units(
            ch, all_units, set(), 0, all_fns, body_font_size, opts
        )
        if ch.items:
            chapters.append(ch)
        discovery_method = "single_section"
        doc.close()
        return BookStructure(
            title=book_title,
            author=book_author,
            source_path=pdf_path,
            chapters=chapters,
            toc_discovery_method=discovery_method,
        )

    raw_toc = [] if opts.force_heuristic_toc else doc.get_toc()
    if raw_toc:
        lvl1 = [(title.strip(), max(1, page)) for lvl, title, page in raw_toc if lvl == 1]
        if len(lvl1) < 2:
            lvl1 = [(title.strip(), max(1, page)) for lvl, title, page in raw_toc]

        chapter_defs: List[Tuple[str, int, int]] = []
        if lvl1 and lvl1[0][1] > p_start:
            chapter_defs.append(("Informações Iniciais", p_start, min(p_end, lvl1[0][1] - 1)))

        for i, (ch_title, ch_page) in enumerate(lvl1):
            next_page = lvl1[i + 1][1] - 1 if i + 1 < len(lvl1) else total_pages
            c_start = max(p_start, ch_page)
            c_end = min(p_end, next_page)
            if c_start <= c_end:
                chapter_defs.append(
                    (normalize_typography(ch_title, opts.normalize_chars), c_start, c_end)
                )

        for ch_title, c_start, c_end in chapter_defs:
            is_toc_chapter = _strip_page_brackets(ch_title).lower() in (
                "contents",
                "table of contents",
                "sumário",
                "sumario",
                "índice",
                "indice",
                "conteúdo",
            )
            if is_toc_chapter and len(chapter_defs) > 1:
                continue

            ch_units = [u for p in range(c_start, c_end + 1) for u in pages_units.get(p, [])]
            ch_fns = [fn for p in range(c_start, c_end + 1) for fn in pages_footnotes.get(p, [])]
            ch = Chapter(
                index=len(chapters) + 1,
                title=ch_title,
                start_page=c_start,
                end_page=c_end,
            )
            _populate_chapter_items_from_units(
                ch, ch_units, set(), 0, ch_fns, body_font_size, opts
            )
            if ch.items:
                chapters.append(ch)
    else:
        toc_pages, printed_entries = _detect_printed_toc_pages(pages_units, total_pages)
        body_units = [
            u
            for p in range(p_start, p_end + 1)
            if p not in toc_pages
            for u in pages_units.get(p, [])
        ]
        # Caso todas as páginas do intervalo selecionado sejam páginas de sumário, mantém todas
        if not body_units:
            body_units = [u for p in range(p_start, p_end + 1) for u in pages_units.get(p, [])]

        spans, consumed_indices, discovery_method = _discover_chapters_from_units(
            body_units=body_units,
            body_font_size=body_font_size,
            printed_entries=printed_entries,
            toc_pages=toc_pages,
            p_start=p_start,
            p_end=p_end,
        )

        # Associa cada nota de rodapé ao último capítulo presente naquela página
        page_last_chapter: Dict[int, Chapter] = {}
        temp_chapters: List[Chapter] = []

        for ch_title, start_u, end_u in spans:
            is_toc_chapter = _strip_page_brackets(ch_title).lower() in (
                "contents",
                "table of contents",
                "sumário",
                "sumario",
                "índice",
                "indice",
                "i n d i c e",
                "conteúdo",
            )
            if is_toc_chapter and len(spans) > 1:
                continue

            u_slice = body_units[start_u:end_u]
            if not u_slice:
                continue

            c_start = u_slice[0].page_num
            c_end = u_slice[-1].page_num
            ch = Chapter(
                index=len(temp_chapters) + 1,
                title=normalize_typography(ch_title, opts.normalize_chars),
                start_page=c_start,
                end_page=c_end,
            )
            _populate_chapter_items_from_units(
                ch,
                u_slice,
                consumed_indices,
                start_u,
                [],
                body_font_size,
                opts,
            )
            if ch.items:
                temp_chapters.append(ch)
                for p in range(c_start, c_end + 1):
                    page_last_chapter[p] = ch

        # Anexa notas de rodapé diferidas ao final do respectivo capítulo
        for p in range(p_start, p_end + 1):
            fns = pages_footnotes.get(p, [])
            if fns and p in page_last_chapter:
                target_ch = page_last_chapter[p]
                if not any(
                    it.kind == "h2" and it.text == "Notas do Capítulo"
                    for it in target_ch.items
                ):
                    target_ch.items.append(
                        ParagraphItem(
                            text="Notas do Capítulo",
                            kind="h2",
                            page_number=target_ch.end_page,
                        )
                    )
                target_ch.items.extend(fns)

        for idx_c, ch in enumerate(temp_chapters, start=1):
            ch.index = idx_c
            chapters.append(ch)

    doc.close()
    return BookStructure(
        title=book_title,
        author=book_author,
        source_path=pdf_path,
        chapters=chapters,
        toc_discovery_method=discovery_method,
    )


def extract_text_or_markdown_book(
    file_path: str,
    options: Optional[EnhancementOptions] = None,
) -> BookStructure:
    opts = options or EnhancementOptions()
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    if opts.normalize_chars:
        content = normalize_typography(content, enabled=True)

    base_title = os.path.splitext(os.path.basename(file_path))[0].replace("_", " ").title()
    chapters: List[Chapter] = []
    current_chapter = Chapter(index=1, title="Início", start_page=1, end_page=1)
    detected_any_chapter = False

    blocks = re.split(r"\n\s*\n", content)
    for block in blocks:
        b = block.strip()
        if not b:
            continue

        if opts.organize_toc and b.startswith("# "):
            detected_any_chapter = True
            if current_chapter.items:
                chapters.append(current_chapter)
            current_chapter = Chapter(
                index=len(chapters) + 1,
                title=b.lstrip("# ").strip(),
                start_page=1,
                end_page=1,
            )
            continue

        is_single_line = "\n" not in b and len(b) <= 90
        if (
            opts.organize_toc
            and is_single_line
            and (
                _CHAPTER_MARKER_RE.match(b)
                or _STANDALONE_CHAPTER_TITLES_RE.match(b)
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

        if b.startswith("## ") or b.startswith("### "):
            current_chapter.items.append(
                ParagraphItem(text=b.lstrip("# ").strip(), kind="h2", page_number=1)
            )
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
            sub_items = all_items[start_i : start_i + chunk_size]
            first_words = " ".join(sub_items[0].text.split()[:6]).rstrip(".,;:") + "..."
            ch = Chapter(
                index=idx,
                title=f"Capítulo {idx} ({first_words})",
                start_page=idx,
                end_page=idx,
                items=sub_items,
            )
            chapters.append(ch)
        method = "auto_segmented_txt"
    else:
        method = "heuristic_txt" if detected_any_chapter else "single_section"

    return BookStructure(
        title=base_title,
        author="Autor Desconhecido",
        source_path=file_path,
        chapters=chapters,
        toc_discovery_method=method,
    )


def extract_epub_book(
    epub_path: str,
    options: Optional[EnhancementOptions] = None,
) -> BookStructure:
    opts = options or EnhancementOptions()
    base_title = os.path.splitext(os.path.basename(epub_path))[0].replace("_", " ").title()
    author = "Autor Desconhecido"
    chapters: List[Chapter] = []

    with zipfile.ZipFile(epub_path, "r") as zf:
        opf_path = None
        if "META-INF/container.xml" in zf.namelist():
            container_xml = ET.fromstring(zf.read("META-INF/container.xml"))
            rootfile = container_xml.find(".//{*}rootfile")
            if rootfile is not None:
                opf_path = rootfile.attrib.get("full-path")

        html_files: List[str] = []
        if opf_path and opf_path in zf.namelist():
            opf_dir = os.path.dirname(opf_path)
            opf_xml = ET.fromstring(zf.read(opf_path))
            t_el = opf_xml.find(".//{*}title")
            if t_el is not None and t_el.text:
                base_title = t_el.text.strip()
            a_el = opf_xml.find(".//{*}creator")
            if a_el is not None and a_el.text:
                author = a_el.text.strip()

            manifest = {
                item.attrib.get("id"): item.attrib.get("href")
                for item in opf_xml.findall(".//{*}manifest/{*}item")
            }
            for itemref in opf_xml.findall(".//{*}spine/{*}itemref"):
                idref = itemref.attrib.get("idref")
                href = manifest.get(idref)
                if href:
                    full_href = f"{opf_dir}/{href}".lstrip("/") if opf_dir else href
                    if full_href in zf.namelist():
                        html_files.append(full_href)

        if not html_files:
            html_files = [
                n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))
            ]

        for idx, hf in enumerate(html_files, start=1):
            raw_html = zf.read(hf).decode("utf-8", errors="replace")
            ch_title = f"Capítulo {idx}"
            m_title = re.search(r"<h[12][^>]*>(.*?)</h[12]>", raw_html, re.I | re.S)
            if m_title:
                ch_title = re.sub(r"<[^>]+>", "", m_title.group(1)).strip() or ch_title

            if opts.normalize_chars:
                ch_title = _format_all_caps_title(normalize_typography(ch_title, True))

            if ch_title.lower() in ("sumário", "sumario", "contents", "table of contents"):
                continue

            ch = Chapter(index=len(chapters) + 1, title=ch_title, start_page=idx, end_page=idx)
            for tag_match in re.finditer(
                r"<(h2|h3|p|li|blockquote)[^>]*>(.*?)</\1>", raw_html, re.I | re.S
            ):
                tag = tag_match.group(1).lower()
                inner = re.sub(r"<[^>]+>", " ", tag_match.group(2))
                inner = reflow_lines_in_block(
                    inner, do_normalize=opts.normalize_chars, do_reflow=opts.reflow_sentences
                )
                if not inner or inner == ch_title or inner == "↑ Voltar ao Sumário":
                    continue
                kind = "h2" if tag in ("h2", "h3") else ("list_item" if tag == "li" else "p")
                ch.items.append(ParagraphItem(text=inner, kind=kind, page_number=idx))

            if ch.items:
                chapters.append(ch)

    return BookStructure(
        title=base_title,
        author=author,
        source_path=epub_path,
        chapters=chapters,
        toc_discovery_method="epub_spine",
    )


def extract_book(
    file_path: str,
    options: Optional[EnhancementOptions] = None,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
) -> BookStructure:
    opts = options or EnhancementOptions()
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return extract_pdf_book(
            file_path,
            options=opts,
            start_page=start_page,
            end_page=end_page,
        )
    elif ext == ".epub":
        return extract_epub_book(file_path, options=opts)
    else:
        return extract_text_or_markdown_book(file_path, options=opts)
