# Role: adapter
"""Parser estrutural de arquivos EPUB baseado em HTMLParser da biblioteca padrão."""

from __future__ import annotations

import os
import posixpath
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

from src.domain.models import BookStructure, Chapter, EnhancementOptions, ParagraphItem
from src.policies.path_policy import validate_page_bounds
from src.policies.text_normalizer import format_all_caps_title, normalize_typography, reflow_lines_in_block

_SKIP_TAGS = {"script", "style", "head", "title"}
_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre", "tr"}
_CONTAINER_BLOCKS = {"div", "section", "article", "aside", "header", "footer", "main"}


class _XhtmlBookParser(HTMLParser):
    """Extrai blocos textuais ordenados de XHTML sem falhar em tags aninhadas ou entidades."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: List[Tuple[str, str]] = []
        self._skip_depth = 0
        self._nav_toc_depth = 0
        self._stack: List[Tuple[str, List[str]]] = []
        self._loose_buf: List[str] = []

    def _flush_loose(self) -> None:
        txt = "".join(self._loose_buf).replace("\xa0", " ").strip()
        self._loose_buf.clear()
        if txt:
            self.blocks.append(("p", txt))

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if t in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if t == "nav" and ("toc" in attr_map.get("epub:type", "").lower() or "doc-toc" in attr_map.get("role", "").lower()):
            self._nav_toc_depth += 1
            return
        if self._skip_depth or self._nav_toc_depth:
            return
        if t == "br" and self._stack:
            self._stack[-1][1].append("\n")
            return
        if t in _BLOCK_TAGS:
            self._flush_loose()
            self._stack.append((t, []))
        elif t in _CONTAINER_BLOCKS:
            if not self._stack:
                self._flush_loose()
            elif self._stack[-1][1] and not self._stack[-1][1][-1].endswith((" ", "\n")):
                self._stack[-1][1].append(" ")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if t == "nav" and self._nav_toc_depth > 0:
            self._nav_toc_depth -= 1
            return
        if self._skip_depth or self._nav_toc_depth:
            return
        if t in _CONTAINER_BLOCKS and not self._stack:
            self._flush_loose()
            return
        if t in _BLOCK_TAGS and self._stack:
            for idx in range(len(self._stack) - 1, -1, -1):
                if self._stack[idx][0] == t:
                    blk_tag, parts = self._stack.pop(idx)
                    txt = "".join(parts).replace("\xa0", " ").strip()
                    if txt:
                        self.blocks.append((blk_tag, txt))
                    break

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._nav_toc_depth:
            return
        if self._stack:
            self._stack[-1][1].append(data)
        else:
            self._loose_buf.append(data)

    def close(self) -> None:
        super().close()
        self._flush_loose()


def _resolve_epub_spine_files(zf: zipfile.ZipFile) -> Tuple[str, str, List[str]]:
    base_title = ""
    author = "Autor Desconhecido"
    opf_path: Optional[str] = None
    name_set = set(zf.namelist())

    if "META-INF/container.xml" in name_set:
        container_xml = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = container_xml.find(".//{*}rootfile")
        if rootfile is not None:
            opf_path = rootfile.attrib.get("full-path")

    html_files: List[str] = []
    seen_files = set()
    if opf_path and opf_path in name_set:
        opf_dir = posixpath.dirname(opf_path)
        opf_xml = ET.fromstring(zf.read(opf_path))
        t_el = opf_xml.find(".//{*}title")
        if t_el is not None and t_el.text:
            base_title = t_el.text.strip()
        a_el = opf_xml.find(".//{*}creator")
        if a_el is not None and a_el.text:
            author = a_el.text.strip()

        manifest: Dict[str, str] = {
            item.attrib.get("id", ""): item.attrib.get("href", "")
            for item in opf_xml.findall(".//{*}manifest/{*}item")
        }
        for itemref in opf_xml.findall(".//{*}spine/{*}itemref"):
            href = manifest.get(itemref.attrib.get("idref", ""), "")
            if not href:
                continue
            clean_href = urllib.parse.unquote(href.split("#", 1)[0])
            joined = posixpath.normpath(posixpath.join(opf_dir, clean_href)) if opf_dir else posixpath.normpath(clean_href)
            if joined in name_set and joined not in seen_files:
                seen_files.add(joined)
                html_files.append(joined)

    if not html_files:
        html_files = [n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
    return base_title, author, html_files


def extract_epub_book(
    epub_path: str,
    options: Optional[EnhancementOptions] = None,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
) -> BookStructure:
    """Extrai capítulos de um arquivo EPUB com suporte a filtro de capítulos (start/end)."""
    validate_page_bounds(start_page, end_page)
    opts = options or EnhancementOptions()
    fallback_title = os.path.splitext(os.path.basename(epub_path))[0].replace("_", " ").title()
    chapters: List[Chapter] = []

    with zipfile.ZipFile(epub_path, "r") as zf:
        base_title, author, html_files = _resolve_epub_spine_files(zf)
        book_title = base_title or fallback_title

        for idx, hf in enumerate(html_files, start=1):
            raw_html = zf.read(hf).decode("utf-8", errors="replace")
            parser = _XhtmlBookParser()
            parser.feed(raw_html)
            parser.close()

            ch_title = f"Capítulo {idx}"
            first_heading_idx = next((i for i, (tg, _) in enumerate(parser.blocks) if tg in ("h1", "h2")), None)
            if first_heading_idx is not None:
                ch_title = reflow_lines_in_block(parser.blocks[first_heading_idx][1], opts.normalize_chars, True) or ch_title
            if opts.normalize_chars:
                ch_title = format_all_caps_title(normalize_typography(ch_title, True))

            if ch_title.lower() in ("sumário", "sumario", "contents", "table of contents", "índice", "indice"):
                continue

            ch = Chapter(index=len(chapters) + 1, title=ch_title, start_page=idx, end_page=idx)
            for blk_idx, (tg, raw_txt) in enumerate(parser.blocks):
                if blk_idx == first_heading_idx:
                    continue
                inner = reflow_lines_in_block(raw_txt, opts.normalize_chars, opts.reflow_sentences)
                if not inner or inner == ch_title or inner == "↑ Voltar ao Sumário":
                    continue
                kind = "h2" if tg in ("h1", "h2", "h3", "h4", "h5", "h6") else ("list_item" if tg == "li" else "p")
                ch.items.append(ParagraphItem(text=inner, kind=kind, page_number=idx))

            if ch.items:
                chapters.append(ch)

    if start_page is not None or end_page is not None:
        s_idx = (start_page or 1) - 1
        e_idx = end_page if end_page is not None else len(chapters)
        chapters = chapters[s_idx:e_idx]
        for new_idx, ch in enumerate(chapters, start=1):
            ch.index = new_idx

    return BookStructure(
        title=book_title,
        author=author,
        source_path=epub_path,
        chapters=chapters,
        toc_discovery_method="epub_spine",
    )
