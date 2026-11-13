# Role: adapter
"""Exportador de livros digitais EPUB 3 acessíveis com rótulos localizados."""

from __future__ import annotations

import datetime
import html
import uuid
import zipfile
from typing import List, Tuple

from src.adapters.atomic_file_writer import write_atomically
from src.domain.models import BookStructure, Chapter
from src.policies.i18n_labels import get_ui_book_labels

_EPUB_STYLE_CSS = """\
body { font-family: Georgia, "Times New Roman", serif; line-height: 1.65; margin: 1.2em; color: #111111; background-color: #ffffff; }
h1 { font-size: 1.6em; margin-top: 1em; margin-bottom: 0.8em; border-bottom: 1px solid #cccccc; padding-bottom: 0.3em; }
h2 { font-size: 1.3em; margin-top: 1.4em; margin-bottom: 0.5em; }
p { margin-top: 0.5em; margin-bottom: 0.8em; text-align: justify; }
p.original-text { font-size: 0.92em; color: #444444; font-style: italic; background-color: #f6f6f6; border-left: 3px solid #999999; padding: 0.4em 0.7em; margin-bottom: 0.25em; }
p.translated-text { margin-top: 0.15em; margin-bottom: 1.1em; }
p.footnote-item { font-size: 0.9em; color: #333333; margin-left: 1em; margin-bottom: 0.5em; }
.list-item { margin-left: 1.2em; margin-bottom: 0.6em; }
"""


def _render_chapter_xhtml(
    chapter: Chapter,
    lang: str,
    source_lang: str,
    bilingual: bool,
    include_back_to_toc: bool,
    back_label: str,
) -> str:
    ch_title = html.escape(chapter.translated_title or chapter.title)
    orig_title = html.escape(chapter.title)
    esc_src = html.escape(source_lang)

    body_lines: List[str] = []
    if bilingual and chapter.translated_title and chapter.translated_title.strip() != chapter.title.strip():
        body_lines.append(f'<p class="original-text" lang="{esc_src}">{orig_title}</p>')
    body_lines.append(f"<h1>{ch_title}</h1>")

    for item in chapter.items:
        orig_esc = html.escape(item.text)
        trans_esc = html.escape(item.translated_text or item.text)

        if item.kind in ("h2", "h3"):
            if bilingual and item.translated_text and item.translated_text.strip() != item.text.strip():
                body_lines.append(f'<p class="original-text" lang="{esc_src}">{orig_esc}</p>')
            body_lines.append(f"<h2>{trans_esc}</h2>")
        elif item.kind == "footnote":
            if bilingual and item.translated_text and item.translated_text.strip() != item.text.strip():
                body_lines.append(f'<p class="original-text footnote-item" lang="{esc_src}">{orig_esc}</p>')
            body_lines.append(f'<p class="footnote-item">{trans_esc}</p>')
        elif item.kind == "list_item":
            if bilingual:
                body_lines.append(f'<p class="original-text list-item" lang="{esc_src}">{orig_esc}</p>')
                body_lines.append(f'<p class="translated-text list-item">{trans_esc}</p>')
            else:
                body_lines.append(f'<p class="list-item">{trans_esc}</p>')
        else:
            if bilingual:
                body_lines.append(f'<p class="original-text" lang="{esc_src}">{orig_esc}</p>')
                body_lines.append(f'<p class="translated-text">{trans_esc}</p>')
            else:
                body_lines.append(f"<p>{trans_esc}</p>")

    if include_back_to_toc:
        body_lines.append(f'<p><a href="nav.xhtml">{html.escape(back_label)}</a></p>')

    body_content = "\n    ".join(body_lines)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{html.escape(lang)}" lang="{html.escape(lang)}">\n'
        f"<head>\n  <meta charset=\"utf-8\" />\n  <title>{ch_title}</title>\n  <link rel=\"stylesheet\" type=\"text/css\" href=\"style.css\" />\n</head>\n"
        f"<body>\n  <section epub:type=\"chapter\">\n    {body_content}\n  </section>\n</body>\n</html>\n"
    )


def build_epub(
    book: BookStructure,
    output_path: str,
    target_lang: str = "pt",
    source_lang: str = "en",
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    """Cria um arquivo EPUB 3 acessível com sumário navegável e escrita atômica."""
    labels = get_ui_book_labels(target_lang)
    eff_src = book.detected_source_lang or (source_lang if source_lang != "auto" else target_lang)
    book_uuid = str(uuid.uuid4())
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    display_book_title = book.title
    if bilingual and book.original_title and book.original_title.strip() != book.title.strip():
        display_book_title = f"{book.title} ({book.original_title})"
    book_title = html.escape(display_book_title)
    book_author = html.escape(book.author)

    chapter_files: List[Tuple[str, str, str]] = [
        (f"chap_{idx:03d}", f"chapter_{idx:03d}.xhtml", ch.translated_title or ch.title)
        for idx, ch in enumerate(book.chapters, start=1)
    ]

    container_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>\n'
        '</container>\n'
    )
    nav_items = "\n        ".join(f'<li><a href="{fn}">{html.escape(ct)}</a></li>' for _, fn, ct in chapter_files)
    nav_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{html.escape(target_lang)}" lang="{html.escape(target_lang)}">\n'
        f"<head><meta charset=\"utf-8\" /><title>{html.escape(labels.toc_title)} - {book_title}</title><link rel=\"stylesheet\" type=\"text/css\" href=\"style.css\" /></head>\n"
        f"<body><nav epub:type=\"toc\" id=\"toc\" role=\"doc-toc\"><h1>{html.escape(labels.toc_title)}</h1><ol>{nav_items}</ol></nav></body>\n</html>\n"
    )
    ncx_points = "\n    ".join(
        f'<navPoint id="navPoint-{i}" playOrder="{i}"><navLabel><text>{html.escape(ct)}</text></navLabel><content src="{fn}"/></navPoint>'
        for i, (_, fn, ct) in enumerate(chapter_files, start=1)
    )
    toc_ncx = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        f'  <head><meta name="dtb:uid" content="urn:uuid:{book_uuid}"/><meta name="dtb:depth" content="1"/></head>\n'
        f"  <docTitle><text>{book_title}</text></docTitle>\n  <navMap>\n    {ncx_points}\n  </navMap>\n</ncx>\n"
    )
    manifest = [
        '<item id="style" href="style.css" media-type="text/css"/>',
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
    ] + [f'<item id="{cid}" href="{fn}" media-type="application/xhtml+xml"/>' for cid, fn, _ in chapter_files]
    spine = ['<itemref idref="nav"/>'] + [f'<itemref idref="{cid}"/>' for cid, _, _ in chapter_files]
    content_opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="BookId">urn:uuid:{book_uuid}</dc:identifier>\n'
        f'    <dc:title>{book_title}</dc:title>\n    <dc:creator>{book_author}</dc:creator>\n'
        f'    <dc:language>{html.escape(target_lang)}</dc:language>\n    <meta property="dcterms:modified">{now_iso}</meta>\n'
        '  </metadata>\n  <manifest>\n    ' + "\n    ".join(manifest) + '\n  </manifest>\n  <spine toc="ncx">\n    ' + "\n    ".join(spine) + '\n  </spine>\n</package>\n'
    )

    def _write(tmp_path: str) -> None:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", container_xml)
            zf.writestr("OEBPS/style.css", _EPUB_STYLE_CSS)
            zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
            zf.writestr("OEBPS/toc.ncx", toc_ncx)
            zf.writestr("OEBPS/content.opf", content_opf)
            for ch, (_cid, fname, _ct) in zip(book.chapters, chapter_files):
                zf.writestr(
                    f"OEBPS/{fname}",
                    _render_chapter_xhtml(ch, target_lang, eff_src, bilingual, include_back_to_toc, labels.back_to_toc),
                )

    return write_atomically(output_path, _write, temp_prefix=".tmp_epub")
