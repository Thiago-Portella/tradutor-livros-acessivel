# Role: adapter
"""Exportador HTML5 único acessível para leitores de tela."""

from __future__ import annotations

import html
from typing import List

from src.adapters.atomic_file_writer import write_atomically
from src.domain.models import BookStructure
from src.policies.i18n_labels import get_ui_book_labels

_HTML_CSS = """
    body { font-family: Georgia, "Segoe UI", serif; line-height: 1.7; max-width: 820px; margin: 0 auto; padding: 1.5rem; color: #1a1a1a; background-color: #fafafa; }
    header { border-bottom: 2px solid #333; margin-bottom: 1.5rem; padding-bottom: 1rem; }
    nav#sumario { background: #ffffff; border: 1px solid #cccccc; border-radius: 6px; padding: 1.2rem 1.8rem; margin-bottom: 2.5rem; }
    nav#sumario ol { line-height: 1.8; }
    section { background: #ffffff; border: 1px solid #e0e0e0; border-radius: 6px; padding: 1.8rem; margin-bottom: 2rem; }
    h1 { font-size: 1.65rem; border-bottom: 1px solid #dddddd; padding-bottom: 0.4rem; }
    h2 { font-size: 1.3rem; margin-top: 1.5rem; }
    p { margin-top: 0.6rem; margin-bottom: 0.9rem; text-align: justify; }
    p.original-text { font-size: 0.93rem; color: #444444; font-style: italic; background-color: #f2f4f7; border-left: 4px solid #7a8b99; padding: 0.5rem 0.8rem; margin-bottom: 0.25rem; }
    p.translated-text { margin-top: 0.2rem; margin-bottom: 1.2rem; }
    p.footnote-item { font-size: 0.9rem; color: #333333; margin-left: 1.2rem; }
    .list-item { margin-left: 1.5rem; }
    .back-to-toc { font-size: 0.9rem; text-decoration: none; }
"""


def build_html(
    book: BookStructure,
    output_path: str,
    target_lang: str = "pt",
    source_lang: str = "en",
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    """Gera página HTML5 única acessível com rótulos localizados e lang real."""
    labels = get_ui_book_labels(target_lang)
    eff_src = book.detected_source_lang or (source_lang if source_lang != "auto" else target_lang)
    esc_src = html.escape(eff_src)
    book_title = html.escape(book.title)
    book_author = html.escape(book.author)

    orig_title_hdr = ""
    if bilingual and book.original_title and book.original_title.strip() != book.title.strip():
        orig_title_hdr = f'\n    <p class="original-text" lang="{esc_src}">{html.escape(book.original_title)}</p>'

    toc_links: List[str] = []
    sections_html: List[str] = []

    for idx, ch in enumerate(book.chapters, start=1):
        ch_id = f"capitulo-{idx}"
        ch_title = html.escape(ch.translated_title or ch.title)
        orig_title = html.escape(ch.title)
        toc_links.append(f'<li><a href="#{ch_id}">{ch_title}</a></li>')

        sec_lines: List[str] = [f'<section id="{ch_id}" aria-labelledby="h1-{ch_id}">']
        if bilingual and ch.translated_title and ch.translated_title.strip() != ch.title.strip():
            sec_lines.append(f'<p class="original-text" lang="{esc_src}">{orig_title}</p>')
        sec_lines.append(f'<h1 id="h1-{ch_id}">{ch_title}</h1>')

        for item in ch.items:
            orig_esc = html.escape(item.text)
            trans_esc = html.escape(item.translated_text or item.text)

            if item.kind in ("h2", "h3"):
                if bilingual and item.translated_text and item.translated_text.strip() != item.text.strip():
                    sec_lines.append(f'<p class="original-text" lang="{esc_src}">{orig_esc}</p>')
                sec_lines.append(f"<h2>{trans_esc}</h2>")
            elif item.kind == "footnote":
                if bilingual and item.translated_text and item.translated_text.strip() != item.text.strip():
                    sec_lines.append(f'<p class="original-text footnote-item" lang="{esc_src}">{orig_esc}</p>')
                sec_lines.append(f'<p class="footnote-item">{trans_esc}</p>')
            elif item.kind == "list_item":
                if bilingual:
                    sec_lines.append(f'<p class="original-text list-item" lang="{esc_src}">{orig_esc}</p>')
                    sec_lines.append(f'<p class="translated-text list-item">{trans_esc}</p>')
                else:
                    sec_lines.append(f'<p class="list-item">{trans_esc}</p>')
            else:
                if bilingual:
                    sec_lines.append(f'<p class="original-text" lang="{esc_src}">{orig_esc}</p>')
                    sec_lines.append(f'<p class="translated-text">{trans_esc}</p>')
                else:
                    sec_lines.append(f"<p>{trans_esc}</p>")

        if include_back_to_toc:
            sec_lines.append(f'<p><a href="#sumario" class="back-to-toc">{html.escape(labels.back_to_toc)}</a></p>')
        sec_lines.append("</section>")
        sections_html.append("\n    ".join(sec_lines))

    full_html = (
        f'<!DOCTYPE html>\n<html lang="{html.escape(target_lang)}">\n<head>\n'
        f'  <meta charset="utf-8" />\n  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        f'  <title>{book_title} - {book_author}</title>\n  <style>{_HTML_CSS}  </style>\n</head>\n'
        f'<body>\n  <header>{orig_title_hdr}\n    <h1>{book_title}</h1>\n'
        f'    <p><strong>{html.escape(labels.author_label)}:</strong> {book_author}</p>\n  </header>\n'
        f'  <nav id="sumario" role="doc-toc" aria-label="{html.escape(labels.toc_title)}">\n'
        f'    <h2>{html.escape(labels.toc_title)}</h2>\n    <ol>\n        ' + "\n        ".join(toc_links) + '\n    </ol>\n  </nav>\n'
        f'  <main>\n  ' + "\n\n  ".join(sections_html) + '\n  </main>\n</body>\n</html>\n'
    )

    def _write(tmp_path: str) -> None:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(full_html)

    return write_atomically(output_path, _write, temp_prefix=".tmp_html")
