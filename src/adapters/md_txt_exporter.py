# Role: adapter
"""Exportadores Markdown (.md) e Texto Puro (.txt) com rótulos localizados."""

from __future__ import annotations

import re
import unicodedata
from typing import List

from src.adapters.atomic_file_writer import write_atomically
from src.domain.models import BookStructure
from src.policies.i18n_labels import get_ui_book_labels


def _slugify_anchor(text: str, idx: int) -> str:
    ascii_t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_t.lower()).strip("-")
    return f"cap-{idx}-{slug}" if slug else f"cap-{idx}"


def build_markdown(
    book: BookStructure,
    output_path: str,
    target_lang: str = "pt",
    source_lang: str = "en",
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    """Gera documento Markdown estruturado com sumário de âncoras e rótulos localizados."""
    labels = get_ui_book_labels(target_lang)
    lines: List[str] = ['<a id="sumario"></a>']
    if bilingual and book.original_title and book.original_title.strip() != book.title.strip():
        lines.append(f"> *{book.original_title}*")
    lines.extend([f"# {book.title}", f"**{labels.author_label}:** {book.author}", "", f"## {labels.toc_title}", ""])

    for idx, ch in enumerate(book.chapters, start=1):
        ch_title = ch.translated_title or ch.title
        lines.append(f"{idx}. [{ch_title}](#{_slugify_anchor(ch_title, idx)})")
    lines.extend(["", "---", ""])

    for idx, ch in enumerate(book.chapters, start=1):
        ch_title = ch.translated_title or ch.title
        lines.append(f'<a id="{_slugify_anchor(ch_title, idx)}"></a>')
        if bilingual and ch.translated_title and ch.translated_title.strip() != ch.title.strip():
            lines.extend([f"> *{ch.title}*", ""])
        lines.extend([f"# {ch_title}", ""])

        for item in ch.items:
            trans = item.translated_text or item.text
            if item.kind in ("h2", "h3"):
                if bilingual and item.translated_text and item.translated_text.strip() != item.text.strip():
                    lines.extend([f"> *{item.text}*", ""])
                lines.extend([f"## {trans}", ""])
            else:
                if bilingual:
                    lines.extend([f"> *{item.text}*", ""])
                lines.extend([trans, ""])

        if include_back_to_toc:
            lines.extend([f"[{labels.back_to_toc}](#sumario)", ""])
        lines.extend(["---", ""])

    content = "\n".join(lines)

    def _write(tmp_path: str) -> None:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)

    return write_atomically(output_path, _write, temp_prefix=".tmp_md")


def build_txt(
    book: BookStructure,
    output_path: str,
    target_lang: str = "pt",
    source_lang: str = "en",
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    """Gera arquivo TXT limpo com sumário localizado e separadores claros."""
    labels = get_ui_book_labels(target_lang)
    sep_major = "=" * 72
    sep_minor = "-" * 72

    lines: List[str] = [sep_major, book.title.upper()]
    if bilingual and book.original_title and book.original_title.strip() != book.title.strip():
        lines.append(f"[Original: {book.original_title}]")
    lines.extend([f"{labels.author_label}: {book.author}", sep_major, "", labels.toc_title.upper(), sep_minor])

    for idx, ch in enumerate(book.chapters, start=1):
        lines.append(f"  {idx:02d}. {ch.translated_title or ch.title}")
    lines.extend([sep_minor, ""])

    for idx, ch in enumerate(book.chapters, start=1):
        ch_title = ch.translated_title or ch.title
        lines.append(sep_major)
        if bilingual and ch.translated_title and ch.translated_title.strip() != ch.title.strip():
            lines.append(f"[Original: {ch.title}]")
        lines.extend([f"{labels.chapter_word.upper()} {idx}: {ch_title.upper()}", sep_major, ""])

        for item in ch.items:
            trans = item.translated_text or item.text
            if item.kind in ("h2", "h3"):
                lines.append("")
                if bilingual and item.translated_text and item.translated_text.strip() != item.text.strip():
                    lines.append(f"  [Original: {item.text}]")
                lines.extend([f"### {trans} ###", ""])
            else:
                if bilingual:
                    lines.append(f"[Original] {item.text}")
                lines.extend([trans, ""])

        if include_back_to_toc:
            lines.extend([labels.end_of_chapter_note, ""])
        lines.append("")

    content = "\n".join(lines)

    def _write(tmp_path: str) -> None:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)

    return write_atomically(output_path, _write, temp_prefix=".tmp_txt")
