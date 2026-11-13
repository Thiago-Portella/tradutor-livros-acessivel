"""
Geradores de livros (traduzidos ou aprimorados) nos 5 formatos suportados:
- EPUB (.epub): Livro digital EPUB 3 acessível com sumário navegável (nav.xhtml + toc.ncx)
- PDF (.pdf): Documento PDF diagramado (A4) com árvore de favoritos/sumário (Bookmarks/Outlines)
  e links clicáveis na página de Sumário
- HTML (.html): Página web única acessível com landmarks ARIA, Sumário navegável e cabeçalhos
- Markdown (.md): Documento estruturado com Sumário de links âncora e cabeçalhos (#, ##)
- Texto Puro (.txt): Texto limpo com Sumário de capítulos no topo e separadores claros
"""

from __future__ import annotations

import datetime
import html
import os
import re
import uuid
import zipfile
from typing import List, Tuple

import pymupdf

from extractor import BookStructure, Chapter

SUPPORTED_FORMATS = {
    "epub": ("Livro Digital EPUB 3 (.epub)", ".epub"),
    "pdf": ("Documento PDF com Marcadores (.pdf)", ".pdf"),
    "html": ("Página Web Acessível HTML5 (.html)", ".html"),
    "md": ("Documento Markdown Estruturado (.md)", ".md"),
    "txt": ("Texto Puro com Sumário (.txt)", ".txt"),
}

_EPUB_STYLE_CSS = """\
body {
    font-family: Georgia, "Times New Roman", serif;
    line-height: 1.65;
    margin: 1.2em;
    color: #111111;
    background-color: #ffffff;
}
h1 {
    font-size: 1.6em;
    margin-top: 1em;
    margin-bottom: 0.8em;
    border-bottom: 1px solid #cccccc;
    padding-bottom: 0.3em;
}
h2 {
    font-size: 1.3em;
    margin-top: 1.4em;
    margin-bottom: 0.5em;
}
p {
    margin-top: 0.5em;
    margin-bottom: 0.8em;
    text-align: justify;
}
p.original-text {
    font-size: 0.92em;
    color: #444444;
    font-style: italic;
    background-color: #f6f6f6;
    border-left: 3px solid #999999;
    padding: 0.4em 0.7em;
    margin-bottom: 0.25em;
}
p.translated-text {
    margin-top: 0.15em;
    margin-bottom: 1.1em;
}
p.footnote-item {
    font-size: 0.9em;
    color: #333333;
    margin-left: 1em;
    margin-bottom: 0.5em;
}
.list-item {
    margin-left: 1.2em;
    margin-bottom: 0.6em;
}
"""


def _render_chapter_xhtml(
    chapter: Chapter,
    lang: str,
    source_lang: str,
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    ch_title = html.escape(chapter.translated_title or chapter.title)
    orig_title = html.escape(chapter.title)

    body_lines: List[str] = []
    if (
        bilingual
        and chapter.translated_title
        and chapter.translated_title.strip() != chapter.title.strip()
    ):
        body_lines.append(
            f'<p class="original-text" lang="{html.escape(source_lang)}">{orig_title}</p>'
        )
    body_lines.append(f"<h1>{ch_title}</h1>")

    for item in chapter.items:
        orig_escaped = html.escape(item.text)
        trans_escaped = html.escape(item.translated_text or item.text)

        if item.kind in ("h2", "h3"):
            if (
                bilingual
                and item.translated_text
                and item.translated_text.strip() != item.text.strip()
            ):
                body_lines.append(
                    f'<p class="original-text" lang="{html.escape(source_lang)}">{orig_escaped}</p>'
                )
            body_lines.append(f"<h2>{trans_escaped}</h2>")
        elif item.kind == "footnote":
            if bilingual and item.translated_text and item.translated_text.strip() != item.text.strip():
                body_lines.append(
                    f'<p class="original-text footnote-item" lang="{html.escape(source_lang)}">{orig_escaped}</p>'
                )
            body_lines.append(f'<p class="footnote-item">{trans_escaped}</p>')
        elif item.kind == "list_item":
            if bilingual:
                body_lines.append(
                    f'<p class="original-text list-item" lang="{html.escape(source_lang)}">{orig_escaped}</p>'
                )
                body_lines.append(f'<p class="translated-text list-item">{trans_escaped}</p>')
            else:
                body_lines.append(f'<p class="list-item">{trans_escaped}</p>')
        else:
            if bilingual:
                body_lines.append(
                    f'<p class="original-text" lang="{html.escape(source_lang)}">{orig_escaped}</p>'
                )
                body_lines.append(f'<p class="translated-text">{trans_escaped}</p>')
            else:
                body_lines.append(f"<p>{trans_escaped}</p>")

    if include_back_to_toc:
        body_lines.append('<p><a href="nav.xhtml">↑ Voltar ao Sumário</a></p>')

    body_content = "\n    ".join(body_lines)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{html.escape(lang)}" lang="{html.escape(lang)}">
<head>
  <meta charset="utf-8" />
  <title>{ch_title}</title>
  <link rel="stylesheet" type="text/css" href="style.css" />
</head>
<body>
  <section epub:type="chapter">
    {body_content}
  </section>
</body>
</html>
"""


def build_epub(
    book: BookStructure,
    output_path: str,
    target_lang: str = "pt",
    source_lang: str = "en",
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    """Cria um arquivo .epub completo e acessível com todos os capítulos do livro."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    book_uuid = str(uuid.uuid4())
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    book_title = html.escape(book.title)
    book_author = html.escape(book.author)

    chapter_files: List[Tuple[str, str, str]] = []
    for idx, ch in enumerate(book.chapters, start=1):
        cid = f"chap_{idx:03d}"
        fname = f"chapter_{idx:03d}.xhtml"
        ctitle = ch.translated_title or ch.title
        chapter_files.append((cid, fname, ctitle))

    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

    nav_items = "\n        ".join(
        f'<li><a href="{fname}">{html.escape(ctitle)}</a></li>'
        for _cid, fname, ctitle in chapter_files
    )
    nav_xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{html.escape(target_lang)}" lang="{html.escape(target_lang)}">
<head>
  <meta charset="utf-8" />
  <title>Sumário - {book_title}</title>
  <link rel="stylesheet" type="text/css" href="style.css" />
</head>
<body>
  <nav epub:type="toc" id="toc" role="doc-toc">
    <h1>Sumário</h1>
    <ol>
        {nav_items}
    </ol>
  </nav>
</body>
</html>
"""

    ncx_points = "\n    ".join(
        f"""<navPoint id="navPoint-{i}" playOrder="{i}">
      <navLabel><text>{html.escape(ctitle)}</text></navLabel>
      <content src="{fname}"/>
    </navPoint>"""
        for i, (_cid, fname, ctitle) in enumerate(chapter_files, start=1)
    )
    toc_ncx = f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="urn:uuid:{book_uuid}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{book_title}</text></docTitle>
  <navMap>
    {ncx_points}
  </navMap>
</ncx>
"""

    manifest_items = [
        '<item id="style" href="style.css" media-type="text/css"/>',
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
    ]
    spine_items = ['<itemref idref="nav"/>']

    for cid, fname, _ctitle in chapter_files:
        manifest_items.append(
            f'<item id="{cid}" href="{fname}" media-type="application/xhtml+xml"/>'
        )
        spine_items.append(f'<itemref idref="{cid}"/>')

    manifest_block = "\n    ".join(manifest_items)
    spine_block = "\n    ".join(spine_items)

    content_opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookId">urn:uuid:{book_uuid}</dc:identifier>
    <dc:title>{book_title}</dc:title>
    <dc:creator>{book_author}</dc:creator>
    <dc:language>{html.escape(target_lang)}</dc:language>
    <meta property="dcterms:modified">{now_iso}</meta>
  </metadata>
  <manifest>
    {manifest_block}
  </manifest>
  <spine toc="ncx">
    {spine_block}
  </spine>
</package>
"""

    tmp_epub = os.path.join(
        os.path.dirname(os.path.abspath(output_path)),
        f".tmp_epub_{os.getpid()}.epub",
    )
    with zipfile.ZipFile(tmp_epub, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/style.css", _EPUB_STYLE_CSS)
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
        zf.writestr("OEBPS/toc.ncx", toc_ncx)
        zf.writestr("OEBPS/content.opf", content_opf)

        for ch, (_cid, fname, _ctitle) in zip(book.chapters, chapter_files):
            ch_xhtml = _render_chapter_xhtml(
                ch,
                lang=target_lang,
                source_lang=source_lang,
                bilingual=bilingual,
                include_back_to_toc=include_back_to_toc,
            )
            zf.writestr(f"OEBPS/{fname}", ch_xhtml)

    os.replace(tmp_epub, output_path)
    return output_path


def build_html(
    book: BookStructure,
    output_path: str,
    target_lang: str = "pt",
    source_lang: str = "en",
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    """
    Gera um arquivo HTML5 único e altamente acessível para leitura direta no navegador com NVDA.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    book_title = html.escape(book.title)
    book_author = html.escape(book.author)

    toc_links: List[str] = []
    sections_html: List[str] = []

    for idx, ch in enumerate(book.chapters, start=1):
        ch_id = f"capitulo-{idx}"
        ch_title = html.escape(ch.translated_title or ch.title)
        orig_title = html.escape(ch.title)

        toc_links.append(f'<li><a href="#{ch_id}">{ch_title}</a></li>')

        sec_lines: List[str] = [f'<section id="{ch_id}" aria-labelledby="h1-{ch_id}">']
        if (
            bilingual
            and ch.translated_title
            and ch.translated_title.strip() != ch.title.strip()
        ):
            sec_lines.append(
                f'<p class="original-text" lang="{html.escape(source_lang)}">{orig_title}</p>'
            )
        sec_lines.append(f'<h1 id="h1-{ch_id}">{ch_title}</h1>')

        for item in ch.items:
            orig_escaped = html.escape(item.text)
            trans_escaped = html.escape(item.translated_text or item.text)

            if item.kind in ("h2", "h3"):
                if (
                    bilingual
                    and item.translated_text
                    and item.translated_text.strip() != item.text.strip()
                ):
                    sec_lines.append(
                        f'<p class="original-text" lang="{html.escape(source_lang)}">{orig_escaped}</p>'
                    )
                sec_lines.append(f"<h2>{trans_escaped}</h2>")
            elif item.kind == "footnote":
                if bilingual and item.translated_text and item.translated_text.strip() != item.text.strip():
                    sec_lines.append(
                        f'<p class="original-text footnote-item" lang="{html.escape(source_lang)}">{orig_escaped}</p>'
                    )
                sec_lines.append(f'<p class="footnote-item">{trans_escaped}</p>')
            elif item.kind == "list_item":
                if bilingual:
                    sec_lines.append(
                        f'<p class="original-text list-item" lang="{html.escape(source_lang)}">{orig_escaped}</p>'
                    )
                    sec_lines.append(f'<p class="translated-text list-item">{trans_escaped}</p>')
                else:
                    sec_lines.append(f'<p class="list-item">{trans_escaped}</p>')
            else:
                if bilingual:
                    sec_lines.append(
                        f'<p class="original-text" lang="{html.escape(source_lang)}">{orig_escaped}</p>'
                    )
                    sec_lines.append(f'<p class="translated-text">{trans_escaped}</p>')
                else:
                    sec_lines.append(f"<p>{trans_escaped}</p>")

        if include_back_to_toc:
            sec_lines.append('<p><a href="#sumario" class="back-to-toc">↑ Voltar ao Sumário</a></p>')
        sec_lines.append("</section>")
        sections_html.append("\n    ".join(sec_lines))

    toc_block = "\n        ".join(toc_links)
    sections_block = "\n\n  ".join(sections_html)

    full_html = f"""<!DOCTYPE html>
<html lang="{html.escape(target_lang)}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{book_title} - {book_author}</title>
  <style>
    body {{
      font-family: Georgia, "Segoe UI", serif;
      line-height: 1.7;
      max-width: 820px;
      margin: 0 auto;
      padding: 1.5rem;
      color: #1a1a1a;
      background-color: #fafafa;
    }}
    header {{
      border-bottom: 2px solid #333;
      margin-bottom: 1.5rem;
      padding-bottom: 1rem;
    }}
    nav#sumario {{
      background: #ffffff;
      border: 1px solid #cccccc;
      border-radius: 6px;
      padding: 1.2rem 1.8rem;
      margin-bottom: 2.5rem;
    }}
    nav#sumario ol {{
      line-height: 1.8;
    }}
    section {{
      background: #ffffff;
      border: 1px solid #e0e0e0;
      border-radius: 6px;
      padding: 1.8rem;
      margin-bottom: 2rem;
    }}
    h1 {{
      font-size: 1.65rem;
      border-bottom: 1px solid #dddddd;
      padding-bottom: 0.4rem;
    }}
    h2 {{
      font-size: 1.3rem;
      margin-top: 1.5rem;
    }}
    p {{
      margin-top: 0.6rem;
      margin-bottom: 0.9rem;
      text-align: justify;
    }}
    p.original-text {{
      font-size: 0.93rem;
      color: #444444;
      font-style: italic;
      background-color: #f2f4f7;
      border-left: 4px solid #7a8b99;
      padding: 0.5rem 0.8rem;
      margin-bottom: 0.25rem;
    }}
    p.translated-text {{
      margin-top: 0.2rem;
      margin-bottom: 1.2rem;
    }}
    p.footnote-item {{
      font-size: 0.9rem;
      color: #333333;
      margin-left: 1.2rem;
    }}
    .list-item {{
      margin-left: 1.5rem;
    }}
    .back-to-toc {{
      font-size: 0.9rem;
      text-decoration: none;
    }}
  </style>
</head>
<body>
  <header>
    <h1>{book_title}</h1>
    <p><strong>Autor:</strong> {book_author}</p>
  </header>

  <nav id="sumario" role="doc-toc" aria-label="Sumário do Livro">
    <h2>Sumário</h2>
    <ol>
        {toc_block}
    </ol>
  </nav>

  <main>
  {sections_block}
  </main>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_html)
    return output_path


def _slugify_anchor(text: str, idx: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return f"cap-{idx}-{slug}" if slug else f"cap-{idx}"


def build_markdown(
    book: BookStructure,
    output_path: str,
    target_lang: str = "pt",
    source_lang: str = "en",
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    """Gera um arquivo Markdown (.md) estruturado com Sumário de links âncora e capítulos."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    lines: List[str] = [
        '<a id="sumario"></a>',
        f"# {book.title}",
        f"**Autor:** {book.author}",
        "",
        "## Sumário",
        "",
    ]

    for idx, ch in enumerate(book.chapters, start=1):
        ch_title = ch.translated_title or ch.title
        anchor = _slugify_anchor(ch_title, idx)
        lines.append(f"{idx}. [{ch_title}](#{anchor})")

    lines.append("")
    lines.append("---")
    lines.append("")

    for idx, ch in enumerate(book.chapters, start=1):
        ch_title = ch.translated_title or ch.title
        anchor = _slugify_anchor(ch_title, idx)
        lines.append(f'<a id="{anchor}"></a>')
        if (
            bilingual
            and ch.translated_title
            and ch.translated_title.strip() != ch.title.strip()
        ):
            lines.append(f"> *{ch.title}*")
            lines.append("")
        lines.append(f"# {ch_title}")
        lines.append("")

        for item in ch.items:
            trans = item.translated_text or item.text
            if item.kind in ("h2", "h3"):
                if (
                    bilingual
                    and item.translated_text
                    and item.translated_text.strip() != item.text.strip()
                ):
                    lines.append(f"> *{item.text}*")
                    lines.append("")
                lines.append(f"## {trans}")
                lines.append("")
            else:
                if bilingual:
                    lines.append(f"> *{item.text}*")
                    lines.append("")
                lines.append(trans)
                lines.append("")

        if include_back_to_toc:
            lines.append("[↑ Voltar ao Sumário](#sumario)")
            lines.append("")

        lines.append("---")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return output_path


def build_txt(
    book: BookStructure,
    output_path: str,
    target_lang: str = "pt",
    source_lang: str = "en",
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    """Gera um arquivo de Texto Puro (.txt) formatado com Sumário completo no início."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    sep_major = "=" * 72
    sep_minor = "-" * 72

    lines: List[str] = [
        sep_major,
        book.title.upper(),
        f"Autor: {book.author}",
        sep_major,
        "",
        "SUMÁRIO",
        sep_minor,
    ]

    for idx, ch in enumerate(book.chapters, start=1):
        ch_title = ch.translated_title or ch.title
        lines.append(f"  {idx:02d}. {ch_title}")

    lines.append(sep_minor)
    lines.append("")

    for idx, ch in enumerate(book.chapters, start=1):
        ch_title = ch.translated_title or ch.title
        lines.append(sep_major)
        if (
            bilingual
            and ch.translated_title
            and ch.translated_title.strip() != ch.title.strip()
        ):
            lines.append(f"[Original: {ch.title}]")
        lines.append(f"CAPÍTULO {idx}: {ch_title.upper()}")
        lines.append(sep_major)
        lines.append("")

        for item in ch.items:
            trans = item.translated_text or item.text
            if item.kind in ("h2", "h3"):
                lines.append("")
                if (
                    bilingual
                    and item.translated_text
                    and item.translated_text.strip() != item.text.strip()
                ):
                    lines.append(f"  [Original: {item.text}]")
                lines.append(f"### {trans} ###")
                lines.append("")
            else:
                if bilingual:
                    lines.append(f"[Original] {item.text}")
                lines.append(trans)
                lines.append("")

        if include_back_to_toc:
            lines.append("[Fim do Capítulo - Consulte o Sumário no início do documento]")
            lines.append("")

        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return output_path


def _load_pdf_fonts() -> Tuple[pymupdf.Font, pymupdf.Font, pymupdf.Font]:
    """
    Carrega fontes Type0 / Identity-H (CID Unicode) nativas do PyMuPDF que preservam
    espaços U+0020 e hifens U+002D puros na tabela /ToUnicode, garantindo leitura limpa
    e detecção de capítulos no ElevenReader.
    """
    return pymupdf.Font("tiro"), pymupdf.Font("tibo"), pymupdf.Font("tiit")


def build_pdf(
    book: BookStructure,
    output_path: str,
    target_lang: str = "pt",
    source_lang: str = "en",
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    """
    Gera um arquivo PDF A4 utilizando a técnica estrutural e tipográfica de sumário e capítulos
    compatível com o ElevenReader (inspirada em 'a terra dá, a terra quer.pdf') aliada a
    /Outlines e links clicáveis para navegadores e leitores de PDF tradicionais:
    1. Fontes TrueType Unicode (Type0 / Identity-H com tabela /ToUnicode) sem glifos .notdef.
    2. Ordem estrita de gravação no Content Stream (/Contents) de cima para baixo (Y crescente),
       garantindo que o título de cada capítulo seja SEMPRE o primeiro bloco (B00) do stream da página.
    3. Sink-drop de abertura de capítulo (y0 ~ 105.5pt = 12.5% da altura da página A4, fora da zona
       superior <10% de cabeçalhos repetitivos) + bloco de título multi-linha (ln >= 2) em 22.5pt Bold
       exclusivo do título principal (subtítulos internos usam itálico 14pt).
    4. Folha de rosto limpa na Página 1, Sumário clicável a partir da Página 2 e árvore /Outlines + /Names.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    page_w, page_h = pymupdf.paper_size("a4")  # (595.0, 842.0)
    margin_x = 68.0
    margin_top = 72.0
    margin_bottom = 52.0
    max_width = page_w - 2 * margin_x

    font_reg, font_bold, font_ital = _load_pdf_fonts()

    def _clean_pdf_text(text: str) -> str:
        if not text:
            return ""
        for ch_invis in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060", "\xad"):
            text = text.replace(ch_invis, "")
        text = text.replace("\u00a0", " ").replace("\u202f", " ")
        return " ".join(text.split())

    def _wrap_text(text: str, font: pymupdf.Font, fsize: float, width_limit: float) -> List[str]:
        cleaned = _clean_pdf_text(text)
        words = cleaned.split()
        if not words:
            return []
        lines: List[str] = []
        curr = words[0]
        for w in words[1:]:
            cand = curr + " " + w
            if font.text_length(cand, fontsize=fsize) <= width_limit:
                curr = cand
            else:
                lines.append(curr)
                curr = w
        lines.append(curr)
        return lines

    LineCmd = Tuple[float, str, str, float, Tuple[float, float, float], bool]

    # Tamanhos calibrados segundo a proporção de 'a terra dá, a terra quer.pdf'
    ch_title_fsize = 22.5
    sub_heading_fsize = 14.0
    body_fsize = 12.5
    bilingual_orig_fsize = 10.5
    footnote_fsize = 10.0

    ch_prefix_word = "Chapter" if target_lang.lower().startswith("en") else "Capítulo"

    def _prepare_chapter_heading(idx: int, raw_title: str) -> Tuple[str, List[str]]:
        """
        Prepara o título de exibição e garante que o bloco B00 do capítulo no PDF tenha
        sempre >= 2 linhas (2 a 4 linhas) em 22.5pt Bold, estrutura que o ElevenReader
        reconhece em 100% dos casos sem confundir com cabeçalhos de página de 1 linha.
        """
        clean_t = _clean_pdf_text(raw_title)
        words = clean_t.split()
        if len(words) <= 1 or len(clean_t) < 15:
            display_title = f"{ch_prefix_word} {idx} — {clean_t}" if clean_t else f"{ch_prefix_word} {idx}"
        else:
            display_title = clean_t

        wrapped = _wrap_text(display_title, font_bold, ch_title_fsize, max_width)
        if len(wrapped) == 1:
            line_str = wrapped[0]
            if " — " in line_str:
                p1, p2 = line_str.split(" — ", 1)
                if p1.strip() and p2.strip():
                    return display_title, [f"{p1.strip()} —", p2.strip()]
            w_list = line_str.split()
            if len(w_list) >= 2:
                total_chars = sum(len(w) for w in w_list)
                best_split = 1
                best_diff = total_chars
                acc = 0
                for split_i in range(1, len(w_list)):
                    acc += len(w_list[split_i - 1])
                    diff = abs(acc - (total_chars - acc))
                    if diff < best_diff:
                        best_diff = diff
                        best_split = split_i
                wrapped = [
                    " ".join(w_list[:best_split]),
                    " ".join(w_list[best_split:]),
                ]
        return display_title, wrapped

    def _layout_chapter_pages(ch: Chapter, idx: int, compact: bool = False) -> Tuple[str, List[List[LineCmd]]]:
        pages: List[List[LineCmd]] = [[]]
        # Sink-drop de abertura de capítulo: inicia y em margin_top + 34.0 (106pt),
        # posicionando o topo da 1ª linha (y0) em ~105.5pt (12.53% da página A4 de 842pt,
        # idêntico aos 12.51% de 'a terra dá, a terra quer.pdf' e fora da margem <10% de cabeçalhos).
        y = margin_top + 34.0
        eff_margin_bottom = 40.0 if compact else margin_bottom
        body_line_h = 16.8 if compact else 18.0
        body_asc = 13.4 if compact else 14.2
        body_desc = body_line_h - body_asc
        para_gap = 4.2 if compact else 8.0
        post_title_gap = 28.0 if compact else 36.0

        def _ensure_space(needed_h: float) -> None:
            nonlocal y
            if y + needed_h > page_h - eff_margin_bottom:
                pages.append([])
                y = margin_top

        raw_ch_title = (ch.translated_title or ch.title).strip()
        display_title, heading_lines = _prepare_chapter_heading(idx, raw_ch_title)
        for ln in heading_lines:
            _ensure_space(28.0)
            y += 23.0
            pages[-1].append((y, ln, "bold", ch_title_fsize, (0.0, 0.0, 0.0), False))
            y += 5.0

        if (
            bilingual
            and ch.translated_title
            and _clean_pdf_text(ch.translated_title) != _clean_pdf_text(ch.title)
        ):
            y += 4.0
            for ln in _wrap_text(ch.title.strip(), font_ital, 11.5, max_width):
                _ensure_space(16.0)
                y += 13.0
                pages[-1].append((y, ln, "ital", 11.5, (0.3, 0.3, 0.3), False))
                y += 3.0

        # Amplo respiro vertical entre o título do capítulo e o 1º parágrafo
        y += post_title_gap

        for item in ch.items:
            orig_txt = _clean_pdf_text(item.text)
            trans_txt = _clean_pdf_text(item.translated_text or item.text)
            if not trans_txt:
                continue

            if item.kind in ("h2", "h3"):
                y += 10.0
                if bilingual and orig_txt != trans_txt:
                    for ln in _wrap_text(orig_txt, font_ital, bilingual_orig_fsize, max_width):
                        _ensure_space(15.0)
                        y += 12.0
                        pages[-1].append((y, ln, "ital", bilingual_orig_fsize, (0.3, 0.3, 0.3), False))
                        y += 3.0
                # Usa Times-Italic (font_ital) nos subtítulos internos para manter Times-Bold (F0)
                # 100% exclusivo do bloco de abertura de capítulo (B00)
                for ln in _wrap_text(trans_txt, font_ital, sub_heading_fsize, max_width):
                    _ensure_space(20.0)
                    y += 16.0
                    pages[-1].append((y, ln, "ital", sub_heading_fsize, (0.08, 0.08, 0.08), False))
                    y += 4.0
                y += 6.0
            elif item.kind == "footnote":
                for ln in _wrap_text(trans_txt, font_reg, footnote_fsize, max_width):
                    _ensure_space(14.5)
                    y += 11.5
                    pages[-1].append((y, ln, "reg", footnote_fsize, (0.22, 0.22, 0.22), False))
                    y += 3.0
                y += 4.0
            else:
                if bilingual:
                    for ln in _wrap_text(orig_txt, font_ital, bilingual_orig_fsize, max_width):
                        _ensure_space(15.0)
                        y += 12.0
                        pages[-1].append((y, ln, "ital", bilingual_orig_fsize, (0.3, 0.3, 0.3), False))
                        y += 3.0
                    y += 2.5
                for ln in _wrap_text(trans_txt, font_reg, body_fsize, max_width):
                    _ensure_space(body_line_h)
                    y += body_asc
                    pages[-1].append((y, ln, "reg", body_fsize, (0.06, 0.06, 0.06), False))
                    y += body_desc
                y += para_gap

        if include_back_to_toc:
            y += 10.0
            _ensure_space(22.0)
            y += 15.0
            pages[-1].append((y, "[Voltar ao Sumário]", "reg", 11.0, (0.0, 0.25, 0.65), True))

        # Evita páginas órfãs de final de capítulo com apenas 1 a 4 linhas soltas (ex.: 'mortuos.')
        if not compact and len(pages) >= 2:
            last_body_lines = [cmd for cmd in pages[-1] if not cmd[5]]
            if 0 < len(last_body_lines) <= 4:
                c_title, c_pages = _layout_chapter_pages(ch, idx, compact=True)
                if len(c_pages) < len(pages):
                    return c_title, c_pages

        return display_title, pages

    chapter_display_titles: List[str] = []
    all_chapters_pages: List[List[List[LineCmd]]] = []
    for idx, ch in enumerate(book.chapters, start=1):
        disp_title, ch_pgs = _layout_chapter_pages(ch, idx)
        chapter_display_titles.append(disp_title)
        all_chapters_pages.append(ch_pgs)

    # Calcula quantas páginas o Sumário ocupará (iniciando na Página 2, após a Folha de Rosto na Página 1)
    toc_entries_wrapped: List[List[str]] = []
    for idx, disp_title in enumerate(chapter_display_titles, start=1):
        sample_label = f"{idx:02d}. {disp_title} — Pág. 999"
        toc_entries_wrapped.append(_wrap_text(sample_label, font_reg, 12.0, max_width))

    toc_page_count = 1
    sim_y = margin_top + 52.0
    for wrapped_entry in toc_entries_wrapped:
        entry_h = len(wrapped_entry) * 18.0 + 6.0
        if sim_y + entry_h > page_h - margin_bottom:
            toc_page_count += 1
            sim_y = margin_top + 20.0
        sim_y += entry_h

    # Página 1 = Folha de Rosto; Páginas 2..(1 + toc_page_count) = Sumário; depois começam os capítulos
    first_toc_page_1based = 2
    chapter_start_pages: List[int] = []
    running_pg = 1 + toc_page_count + 1
    for ch_pages in all_chapters_pages:
        chapter_start_pages.append(running_pg)
        running_pg += len(ch_pages)

    doc = pymupdf.open()

    # 1. Página 1: Folha de Rosto limpa (Autor + Título do Livro em 22.5pt, igual à pág. 2 de 'a terra dá, a terra quer.pdf')
    title_page = doc.new_page(width=page_w, height=page_h)
    title_y = margin_top + 34.0
    if book.author and _clean_pdf_text(book.author):
        tw_author = pymupdf.TextWriter(title_page.rect)
        for ln in _wrap_text(book.author.strip(), font_reg, 16.5, max_width):
            title_y += 20.0
            tw_author.append((margin_x, title_y), ln, font=font_reg, fontsize=16.5)
            title_y += 4.0
        tw_author.write_text(title_page, color=(0.15, 0.15, 0.15))
        title_y += 18.0

    tw_book_title = pymupdf.TextWriter(title_page.rect)
    for ln in _wrap_text(book.title.strip(), font_bold, ch_title_fsize, max_width):
        title_y += 25.0
        tw_book_title.append((margin_x, title_y), ln, font=font_bold, fontsize=ch_title_fsize)
        title_y += 5.0
    tw_book_title.write_text(title_page, color=(0.0, 0.0, 0.0))

    # 2. Páginas do Sumário (a partir da Página 2)
    for _ in range(toc_page_count):
        doc.new_page(width=page_w, height=page_h)

    curr_toc_pg_idx = first_toc_page_1based - 1  # índice 1 (Página 2)
    toc_y = margin_top + 34.0
    tw_toc_hdr = pymupdf.TextWriter(doc[curr_toc_pg_idx].rect)
    toc_y += 23.0
    tw_toc_hdr.append(
        (margin_x, toc_y),
        "Sumário",
        font=font_bold,
        fontsize=ch_title_fsize,
    )
    toc_y += 28.0
    tw_toc_hdr.write_text(doc[curr_toc_pg_idx], color=(0.0, 0.0, 0.0))

    pending_toc_links: List[Tuple[int, pymupdf.Rect, int]] = []
    pending_toc_underlines: List[Tuple[int, float, float]] = []
    curr_toc_tw = pymupdf.TextWriter(doc[curr_toc_pg_idx].rect)

    for idx, (disp_title, target_pg_1based) in enumerate(zip(chapter_display_titles, chapter_start_pages), start=1):
        label = f"{idx:02d}. {disp_title} — Pág. {target_pg_1based}"
        wrapped_lines = _wrap_text(label, font_reg, 12.0, max_width)
        entry_h = len(wrapped_lines) * 18.0 + 6.0

        if toc_y + entry_h > page_h - margin_bottom and (curr_toc_pg_idx + 1) < (1 + toc_page_count):
            curr_toc_tw.write_text(doc[curr_toc_pg_idx], color=(0.0, 0.25, 0.65))
            curr_toc_pg_idx += 1
            toc_y = margin_top + 10.0
            curr_toc_tw = pymupdf.TextWriter(doc[curr_toc_pg_idx].rect)

        entry_top_y = toc_y + 2.0
        max_line_w = 120.0
        for ln in wrapped_lines:
            toc_y += 14.5
            curr_toc_tw.append((margin_x, toc_y), ln, font=font_reg, fontsize=12.0)
            lw = font_reg.text_length(ln, fontsize=12.0)
            if lw > max_line_w:
                max_line_w = lw
            toc_y += 3.5
        toc_y += 6.0
        entry_bottom_y = toc_y - 2.0

        pending_toc_underlines.append((curr_toc_pg_idx, entry_bottom_y - 1.5, min(max_width, max_line_w)))
        link_rect = pymupdf.Rect(margin_x - 2.0, entry_top_y, margin_x + max_width, entry_bottom_y + 2.0)
        pending_toc_links.append((curr_toc_pg_idx, link_rect, target_pg_1based - 1))

    curr_toc_tw.write_text(doc[curr_toc_pg_idx], color=(0.0, 0.25, 0.65))
    for u_pg_idx, u_y, u_w in pending_toc_underlines:
        doc[u_pg_idx].draw_line(
            pymupdf.Point(margin_x, u_y),
            pymupdf.Point(margin_x + u_w, u_y),
            color=(0.0, 0.25, 0.65),
            width=0.5,
        )

    # 3. Páginas dos Capítulos: gravadas em ORDEM ESTRITA DE LEITURA (de cima para baixo no Content Stream!)
    pending_back_links: List[Tuple[int, pymupdf.Rect]] = []
    toc_bookmarks: List[List[object]] = [[1, "Sumário", first_toc_page_1based]]

    font_map = {
        "reg": font_reg,
        "bold": font_bold,
        "ital": font_ital,
    }

    for disp_title, ch_pages, start_pg_1based in zip(chapter_display_titles, all_chapters_pages, chapter_start_pages):
        toc_bookmarks.append([1, disp_title, start_pg_1based])

        for p_lines in ch_pages:
            page = doc.new_page(width=page_w, height=page_h)
            pg_idx = page.number

            # Único TextWriter por página para gerar um único bloco BT..ET sem duplicar fontes F1/F2
            page_tw = pymupdf.TextWriter(page.rect)
            back_cmds: List[Tuple[float, str, float, Tuple[float, float, float]]] = []

            for y_base, txt, fkind, fsize, color, is_back in p_lines:
                if is_back:
                    back_cmds.append((y_base, txt, fsize, color))
                    continue
                page_tw.append((margin_x, y_base), txt, font=font_map.get(fkind, font_reg), fontsize=fsize)

            num_str = str(pg_idx + 1)
            nw = font_reg.text_length(num_str, fontsize=9.5)
            page_tw.append(((page_w - nw) / 2.0, page_h - 28.0), num_str, font=font_reg, fontsize=9.5)
            page_tw.write_text(page, color=(0.0, 0.0, 0.0))

            for y_base, txt, fsize, color in back_cmds:
                tw_back = pymupdf.TextWriter(page.rect)
                tw_back.append((margin_x, y_base), txt, font=font_reg, fontsize=fsize)
                tw_back.write_text(page, color=color)
                bw = font_reg.text_length(txt, fontsize=fsize)
                brect = pymupdf.Rect(margin_x - 2.0, y_base - fsize - 2.0, margin_x + bw + 4.0, y_base + 4.0)
                pending_back_links.append((pg_idx, brect))

    for toc_pg_idx, lrect, target_zero_idx in pending_toc_links:
        doc[toc_pg_idx].insert_link(
            {
                "kind": pymupdf.LINK_GOTO,
                "from": lrect,
                "page": target_zero_idx,
                "to": pymupdf.Point(margin_x, margin_top),
            }
        )

    for pg_idx, brect in pending_back_links:
        doc[pg_idx].insert_link(
            {
                "kind": pymupdf.LINK_GOTO,
                "from": brect,
                "page": first_toc_page_1based - 1,
                "to": pymupdf.Point(margin_x, margin_top),
            }
        )

    doc.set_metadata({"title": _clean_pdf_text(book.title), "author": _clean_pdf_text(book.author)})
    doc.set_toc(toc_bookmarks)

    names_entries: List[str] = []
    for idx, (_lvl, _btitle, bpage_1based) in enumerate(toc_bookmarks):
        pg_zero = max(0, min(len(doc) - 1, int(bpage_1based) - 1))
        page_xref = doc[pg_zero].xref
        dest_name = f"chapter.{idx:04d}!"
        dest_obj_xref = doc.get_new_xref()
        doc.update_object(
            dest_obj_xref,
            f"<< /D [ {page_xref} 0 R /XYZ 0 {int(page_h)} null ] >>",
        )
        names_entries.append(f"({dest_name}) {dest_obj_xref} 0 R")

    dests_leaf_xref = doc.get_new_xref()
    first_name = "chapter.0000!"
    last_name = f"chapter.{len(toc_bookmarks) - 1:04d}!"
    doc.update_object(
        dests_leaf_xref,
        f"<< /Names [ {' '.join(names_entries)} ] /Limits [ ({first_name}) ({last_name}) ] >>",
    )
    names_dict_xref = doc.get_new_xref()
    doc.update_object(names_dict_xref, f"<< /Dests {dests_leaf_xref} 0 R >>")

    cat_xref = doc.pdf_catalog()
    doc.xref_set_key(cat_xref, "PageMode", "/UseOutlines")
    doc.xref_set_key(cat_xref, "Names", f"{names_dict_xref} 0 R")

    for pg in doc:
        for lnk in pg.get_links():
            lxref = lnk.get("xref")
            target_pg = lnk.get("page", 0)
            if lxref and 0 <= target_pg < len(doc):
                t_page_xref = doc[target_pg].xref
                r = lnk["from"]
                pdf_y0 = page_h - r.y1
                pdf_y1 = page_h - r.y0
                doc.update_object(
                    lxref,
                    f"<< /Type /Annot /Subtype /Link /F 4 /Border [ 0 0 0 ] "
                    f"/Rect [ {r.x0:.2f} {pdf_y0:.2f} {r.x1:.2f} {pdf_y1:.2f} ] "
                    f"/Dest [ {t_page_xref} 0 R /XYZ 0 {int(page_h)} null ] "
                    f"/A << /S /GoTo /D [ {t_page_xref} 0 R /XYZ 0 {int(page_h)} null ] >> >>",
                )

    tmp_path = os.path.join(
        os.path.dirname(os.path.abspath(output_path)),
        f".tmp_pdf_{os.getpid()}.pdf",
    )
    doc.save(tmp_path, garbage=4, deflate=True, clean=True)
    doc.close()
    os.replace(tmp_path, output_path)
    return output_path


def export_book(
    book: BookStructure,
    output_path: str,
    fmt: str = "epub",
    target_lang: str = "pt",
    source_lang: str = "en",
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    """Exporta a estrutura do livro para o formato escolhido (epub, pdf, html, md, txt)."""
    fmt_clean = fmt.lower().lstrip(".")
    if fmt_clean == "markdown":
        fmt_clean = "md"

    if fmt_clean == "epub":
        return build_epub(
            book,
            output_path,
            target_lang=target_lang,
            source_lang=source_lang,
            bilingual=bilingual,
            include_back_to_toc=include_back_to_toc,
        )
    elif fmt_clean == "pdf":
        return build_pdf(
            book,
            output_path,
            target_lang=target_lang,
            source_lang=source_lang,
            bilingual=bilingual,
            include_back_to_toc=include_back_to_toc,
        )
    elif fmt_clean == "html":
        return build_html(
            book,
            output_path,
            target_lang=target_lang,
            source_lang=source_lang,
            bilingual=bilingual,
            include_back_to_toc=include_back_to_toc,
        )
    elif fmt_clean == "md":
        return build_markdown(
            book,
            output_path,
            target_lang=target_lang,
            source_lang=source_lang,
            bilingual=bilingual,
            include_back_to_toc=include_back_to_toc,
        )
    elif fmt_clean == "txt":
        return build_txt(
            book,
            output_path,
            target_lang=target_lang,
            source_lang=source_lang,
            bilingual=bilingual,
            include_back_to_toc=include_back_to_toc,
        )
    else:
        raise ValueError(f"Formato de saída não suportado: {fmt}")
