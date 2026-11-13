# Role: adapter
"""Exportador de documentos PDF A4 com Sumário clicável, /Outlines e /Names seguros."""

from __future__ import annotations

from typing import List, Tuple

import pymupdf

from src.adapters.atomic_file_writer import write_atomically
from src.adapters.pdf_fonts_layout import (
    LineCmd,
    clean_pdf_text,
    escape_pdf_string,
    layout_chapter_pages,
    load_pdf_fonts,
    wrap_pdf_text,
)
from src.domain.models import BookStructure
from src.policies.i18n_labels import get_ui_book_labels


def build_pdf(
    book: BookStructure,
    output_path: str,
    target_lang: str = "pt",
    source_lang: str = "en",
    bilingual: bool = False,
    include_back_to_toc: bool = False,
) -> str:
    """Gera PDF A4 acessível com fontes Unicode, /Outlines, links internos e gravação atômica."""
    labels = get_ui_book_labels(target_lang)
    page_w, page_h = pymupdf.paper_size("a4")
    margin_x, margin_top, margin_bottom = 68.0, 72.0, 52.0
    max_width = page_w - 2 * margin_x
    page_dims = (page_w, page_h, margin_x, margin_top, margin_bottom)

    fonts = load_pdf_fonts(book, labels)
    font_reg, font_bold, font_ital = fonts
    font_map = {"reg": font_reg, "bold": font_bold, "ital": font_ital}

    chapter_display_titles: List[str] = []
    all_chapters_pages: List[List[List[LineCmd]]] = []
    for idx, ch in enumerate(book.chapters, start=1):
        disp_title, ch_pgs = layout_chapter_pages(
            ch, idx, labels, fonts, page_dims, bilingual, include_back_to_toc
        )
        chapter_display_titles.append(disp_title)
        all_chapters_pages.append(ch_pgs)

    toc_page_count = 1
    sim_y = margin_top + 52.0
    for idx, disp_title in enumerate(chapter_display_titles, start=1):
        wrapped_sample = wrap_pdf_text(f"{idx:02d}. {disp_title} — {labels.page_abbr} 999", font_reg, 12.0, max_width)
        entry_h = len(wrapped_sample) * 18.0 + 6.0
        if sim_y + entry_h > page_h - margin_bottom:
            toc_page_count += 1
            sim_y = margin_top + 20.0
        sim_y += entry_h

    first_toc_page_1based = 2
    chapter_start_pages: List[int] = []
    running_pg = 1 + toc_page_count + 1
    for ch_pages in all_chapters_pages:
        chapter_start_pages.append(running_pg)
        running_pg += len(ch_pages)

    doc = pymupdf.open()
    try:
        title_page = doc.new_page(width=page_w, height=page_h)
        title_y = margin_top + 34.0
        if book.author and clean_pdf_text(book.author):
            tw_author = pymupdf.TextWriter(title_page.rect)
            for ln in wrap_pdf_text(book.author.strip(), font_reg, 16.5, max_width):
                title_y += 20.0
                tw_author.append((margin_x, title_y), ln, font=font_reg, fontsize=16.5)
                title_y += 4.0
            tw_author.write_text(title_page, color=(0.15, 0.15, 0.15))
            title_y += 18.0

        tw_title = pymupdf.TextWriter(title_page.rect)
        for ln in wrap_pdf_text(book.title.strip(), font_bold, 22.5, max_width):
            title_y += 25.0
            tw_title.append((margin_x, title_y), ln, font=font_bold, fontsize=22.5)
            title_y += 5.0
        tw_title.write_text(title_page, color=(0.0, 0.0, 0.0))

        if bilingual and book.original_title and clean_pdf_text(book.original_title) != clean_pdf_text(book.title):
            title_y += 12.0
            tw_orig = pymupdf.TextWriter(title_page.rect)
            for ln in wrap_pdf_text(book.original_title.strip(), font_ital, 13.0, max_width):
                title_y += 16.0
                tw_orig.append((margin_x, title_y), ln, font=font_ital, fontsize=13.0)
                title_y += 3.0
            tw_orig.write_text(title_page, color=(0.3, 0.3, 0.3))

        for _ in range(toc_page_count):
            doc.new_page(width=page_w, height=page_h)

        curr_toc_idx = first_toc_page_1based - 1
        toc_y = margin_top + 34.0
        tw_toc_hdr = pymupdf.TextWriter(doc[curr_toc_idx].rect)
        toc_y += 23.0
        tw_toc_hdr.append((margin_x, toc_y), labels.toc_title, font=font_bold, fontsize=22.5)
        toc_y += 28.0
        tw_toc_hdr.write_text(doc[curr_toc_idx], color=(0.0, 0.0, 0.0))

        pending_toc_links: List[Tuple[int, pymupdf.Rect, int]] = []
        pending_underlines: List[Tuple[int, float, float]] = []
        curr_toc_tw = pymupdf.TextWriter(doc[curr_toc_idx].rect)

        for idx, (disp_title, target_pg) in enumerate(zip(chapter_display_titles, chapter_start_pages), start=1):
            label = f"{idx:02d}. {disp_title} — {labels.page_abbr} {target_pg}"
            wrapped = wrap_pdf_text(label, font_reg, 12.0, max_width)
            entry_h = len(wrapped) * 18.0 + 6.0
            if toc_y + entry_h > page_h - margin_bottom and (curr_toc_idx + 1) < (1 + toc_page_count):
                curr_toc_tw.write_text(doc[curr_toc_idx], color=(0.0, 0.25, 0.65))
                curr_toc_idx += 1
                toc_y = margin_top + 10.0
                curr_toc_tw = pymupdf.TextWriter(doc[curr_toc_idx].rect)

            entry_top = toc_y + 2.0
            max_lw = 120.0
            for ln in wrapped:
                toc_y += 14.5
                curr_toc_tw.append((margin_x, toc_y), ln, font=font_reg, fontsize=12.0)
                max_lw = max(max_lw, font_reg.text_length(ln, fontsize=12.0))
                toc_y += 3.5
            toc_y += 6.0
            pending_underlines.append((curr_toc_idx, toc_y - 3.5, min(max_width, max_lw)))
            pending_toc_links.append((curr_toc_idx, pymupdf.Rect(margin_x - 2.0, entry_top, margin_x + max_width, toc_y), target_pg - 1))

        curr_toc_tw.write_text(doc[curr_toc_idx], color=(0.0, 0.25, 0.65))
        for u_pg, u_y, u_w in pending_underlines:
            doc[u_pg].draw_line(pymupdf.Point(margin_x, u_y), pymupdf.Point(margin_x + u_w, u_y), color=(0.0, 0.25, 0.65), width=0.5)

        pending_back: List[Tuple[int, pymupdf.Rect]] = []
        toc_bookmarks: List[List[object]] = [[1, labels.toc_title, first_toc_page_1based]]
        for disp_title, ch_pages, start_pg in zip(chapter_display_titles, all_chapters_pages, chapter_start_pages):
            toc_bookmarks.append([1, disp_title, start_pg])
            for p_lines in ch_pages:
                page = doc.new_page(width=page_w, height=page_h)
                pg_idx = page.number
                page_tw = pymupdf.TextWriter(page.rect)
                back_cmds: List[Tuple[float, str, float, Tuple[float, float, float]]] = []
                for y_b, txt, fkind, fsize, color, is_back in p_lines:
                    if is_back:
                        back_cmds.append((y_b, txt, fsize, color))
                    else:
                        page_tw.append((margin_x, y_b), txt, font=font_map.get(fkind, font_reg), fontsize=fsize)
                num_str = str(pg_idx + 1)
                page_tw.append(((page_w - font_reg.text_length(num_str, fontsize=9.5)) / 2.0, page_h - 28.0), num_str, font=font_reg, fontsize=9.5)
                page_tw.write_text(page, color=(0.0, 0.0, 0.0))
                for y_b, txt, fsize, color in back_cmds:
                    tw_b = pymupdf.TextWriter(page.rect)
                    tw_b.append((margin_x, y_b), txt, font=font_reg, fontsize=fsize)
                    tw_b.write_text(page, color=color)
                    bw = font_reg.text_length(txt, fontsize=fsize)
                    pending_back.append((pg_idx, pymupdf.Rect(margin_x - 2.0, y_b - fsize - 2.0, margin_x + bw + 4.0, y_b + 4.0)))

        for t_pg, lrect, target_z in pending_toc_links:
            doc[t_pg].insert_link({"kind": pymupdf.LINK_GOTO, "from": lrect, "page": target_z, "to": pymupdf.Point(margin_x, margin_top)})
        for pg_idx, brect in pending_back:
            doc[pg_idx].insert_link({"kind": pymupdf.LINK_GOTO, "from": brect, "page": first_toc_page_1based - 1, "to": pymupdf.Point(margin_x, margin_top)})

        doc.set_metadata({"title": clean_pdf_text(book.title), "author": clean_pdf_text(book.author)})
        doc.set_toc(toc_bookmarks)

        names_pairs: List[Tuple[str, str]] = []
        for idx, (_lvl, _bt, bp) in enumerate(toc_bookmarks):
            pg_zero = max(0, min(len(doc) - 1, int(bp) - 1))
            raw_dest = f"chapter.{idx:04d}:{clean_pdf_text(str(_bt))[:40]}"
            dest_name = escape_pdf_string(raw_dest)
            dest_xref = doc.get_new_xref()
            doc.update_object(dest_xref, f"<< /D [ {doc[pg_zero].xref} 0 R /XYZ 0 {int(page_h)} null ] >>")
            names_pairs.append((raw_dest, f"({dest_name}) {dest_xref} 0 R"))

        names_pairs.sort(key=lambda item: item[0])
        names_entries = [entry for _raw, entry in names_pairs]
        first_name = escape_pdf_string(names_pairs[0][0])
        last_name = escape_pdf_string(names_pairs[-1][0])
        dests_xref = doc.get_new_xref()
        doc.update_object(dests_xref, f"<< /Names [ {' '.join(names_entries)} ] /Limits [ ({first_name}) ({last_name}) ] >>")
        names_xref = doc.get_new_xref()
        doc.update_object(names_xref, f"<< /Dests {dests_xref} 0 R >>")
        cat_xref = doc.pdf_catalog()
        doc.xref_set_key(cat_xref, "PageMode", "/UseOutlines")
        doc.xref_set_key(cat_xref, "Names", f"{names_xref} 0 R")

        for pg in doc:
            for lnk in pg.get_links():
                lxref, target_pg = lnk.get("xref"), lnk.get("page", 0)
                if lxref and 0 <= target_pg < len(doc):
                    t_xref, r = doc[target_pg].xref, lnk["from"]
                    doc.update_object(
                        lxref,
                        f"<< /Type /Annot /Subtype /Link /F 4 /Border [ 0 0 0 ] "
                        f"/Rect [ {r.x0:.2f} {page_h - r.y1:.2f} {r.x1:.2f} {page_h - r.y0:.2f} ] "
                        f"/Dest [ {t_xref} 0 R /XYZ 0 {int(page_h)} null ] "
                        f"/A << /S /GoTo /D [ {t_xref} 0 R /XYZ 0 {int(page_h)} null ] >> >>",
                    )

        return write_atomically(
            output_path,
            lambda tmp_p: doc.save(tmp_p, garbage=4, deflate=True, clean=True),
            temp_prefix=".tmp_pdf",
        )
    finally:
        doc.close()
