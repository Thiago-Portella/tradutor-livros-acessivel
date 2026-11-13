# Role: service
"""Orquestração dos pipelines de tradução e apenas aprimoramento de livros."""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from src.adapters.google_translate_client import google_translate
from src.adapters.sqlite_cache import TranslationCacheDB
from src.domain.models import BookStructure, Chapter, EnhancementOptions, TranslationError
from src.policies.i18n_labels import describe_toc_method
from src.policies.path_policy import (
    ensure_safe_output_path,
    get_default_cache_path,
    make_partial_output_path,
)
from src.services.batch_translator import translate_paragraphs_batch
from src.services.book_io_dispatch import export_book_any, extract_book_any


def enhance_only_book_pipeline(
    input_path: str,
    output_path: str,
    output_format: str = "epub",
    doc_lang: str = "pt",
    options: Optional[EnhancementOptions] = None,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
    status_callback: Optional[Callable[[int, int, str, str], None]] = None,
) -> BookStructure:
    """Executa apenas aprimoramento estrutural/textual sem traduzir e exporta o livro."""
    opts = options or EnhancementOptions()
    output_path = ensure_safe_output_path(
        input_path, output_path, output_format=output_format, target_lang=doc_lang, enhance_only=True
    )
    if status_callback:
        status_callback(10, 100, "Extraindo páginas e aplicando aprimoramentos no livro...", "")

    book = extract_book_any(input_path, options=opts, start_page=start_page, end_page=end_page)
    book.original_title = book.title
    total_paragraphs = sum(len(ch.items) for ch in book.chapters)
    if total_paragraphs == 0:
        raise TranslationError(
            "Nenhum texto selecionável foi encontrado no arquivo. "
            "Este PDF parece ser composto apenas por imagens escaneadas (sem camada de texto/OCR)."
        )

    toc_desc = describe_toc_method(book.toc_discovery_method)
    if status_callback:
        status_callback(
            60,
            100,
            f"Estrutura organizada: {len(book.chapters)} capítulos ({toc_desc}). Gerando {output_format.upper()}...",
            f"Capítulos: {len(book.chapters)} | Parágrafos processados: {total_paragraphs} | Método: {toc_desc}",
        )

    export_book_any(
        book=book,
        output_path=output_path,
        fmt=output_format,
        target_lang=doc_lang,
        source_lang=doc_lang,
        bilingual=False,
        include_back_to_toc=opts.include_back_to_toc,
    )
    if status_callback:
        status_callback(
            100,
            100,
            f"Aprimoramento concluído! {len(book.chapters)} capítulos e {total_paragraphs} parágrafos exportados.",
            f"Arquivo salvo em: {output_path}",
        )
    return book


def _build_partial_book(book: BookStructure) -> BookStructure:
    partial_chapters: List[Chapter] = []
    for ch in book.chapters:
        translated_items = [it for it in ch.items if it.translated_text is not None]
        if translated_items:
            partial_chapters.append(
                Chapter(
                    index=len(partial_chapters) + 1,
                    title=ch.title,
                    start_page=ch.start_page,
                    end_page=ch.end_page,
                    translated_title=ch.translated_title,
                    items=translated_items,
                )
            )
    return BookStructure(
        title=book.title,
        author=book.author,
        source_path=book.source_path,
        chapters=partial_chapters,
        toc_discovery_method=book.toc_discovery_method,
        original_title=book.original_title,
        detected_source_lang=book.detected_source_lang,
    )


def _translate_titles(
    book: BookStructure,
    source_lang: str,
    target_lang: str,
    cache_db: TranslationCacheDB,
    cancel_check: Optional[Callable[[], bool]],
    detected_sink: List[str],
) -> None:
    if book.title:
        cached_title = cache_db.get(book.title, source_lang, target_lang)
        if cached_title:
            book.title = cached_title
        else:
            try:
                t_title, det_t = google_translate(book.title, target_lang, source_lang)
                if t_title:
                    cache_db.put(book.title, t_title, source_lang, target_lang)
                    book.title = t_title
                if det_t and det_t != "auto" and not detected_sink:
                    detected_sink.append(det_t)
            except Exception:
                pass

    raw_titles = [ch.title for ch in book.chapters]
    try:
        translated = translate_paragraphs_batch(
            raw_titles, target_lang, source_lang, cache_db, cancel_check=cancel_check, detected_lang_sink=detected_sink
        )
        for ch, t_ch in zip(book.chapters, translated):
            ch.translated_title = t_ch or ch.title
    except Exception:
        for ch in book.chapters:
            ch.translated_title = ch.title


def translate_book_pipeline(
    input_path: str,
    output_path: str,
    output_format: str = "epub",
    source_lang: str = "auto",
    target_lang: str = "pt",
    bilingual: bool = False,
    options: Optional[EnhancementOptions] = None,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    status_callback: Optional[Callable[[int, int, str, str], None]] = None,
) -> BookStructure:
    """Traduz livro salvando lotes no SQLite WAL e exportando apenas ao concluir ou pausar."""
    opts = options or EnhancementOptions()
    output_path = ensure_safe_output_path(
        input_path, output_path, output_format=output_format, target_lang=target_lang, enhance_only=False
    )
    if status_callback:
        status_callback(0, 100, "Extraindo estrutura, descobrindo capítulos e limpando parágrafos...", "")

    book = extract_book_any(input_path, options=opts, start_page=start_page, end_page=end_page)
    book.original_title = book.title
    toc_desc = describe_toc_method(book.toc_discovery_method)
    if status_callback:
        status_callback(0, 100, f"Estrutura identificada: {len(book.chapters)} capítulos ({toc_desc})", f"Método de sumário: {toc_desc} ({len(book.chapters)} capítulos encontrados)")

    total_paragraphs = sum(len(ch.items) for ch in book.chapters)
    if total_paragraphs == 0:
        raise TranslationError("Nenhum texto selecionável foi encontrado no arquivo. Este PDF parece ser composto apenas por imagens escaneadas.")

    cache_db = TranslationCacheDB(get_default_cache_path(input_path))
    detected_sink: List[str] = []
    _translate_titles(book, source_lang, target_lang, cache_db, cancel_check, detected_sink)

    groups: List[List[Tuple[int, Chapter]]] = []
    curr_grp: List[Tuple[int, Chapter]] = []
    curr_cnt = 0
    for ch_idx, ch in enumerate(book.chapters, start=1):
        curr_grp.append((ch_idx, ch))
        curr_cnt += len(ch.items)
        if curr_cnt >= 20:
            groups.append(curr_grp)
            curr_grp, curr_cnt = [], 0
    if curr_grp:
        groups.append(curr_grp)

    processed_so_far = 0
    was_cancelled = False
    for group in groups:
        if cancel_check and cancel_check():
            was_cancelled = True
            break
        f_idx, f_ch = group[0]
        l_idx, l_ch = group[-1]
        ch_label = (
            f"Capítulo {f_idx}/{len(book.chapters)}: {f_ch.translated_title}"
            if len(group) == 1
            else f"Capítulos {f_idx} a {l_idx}/{len(book.chapters)}: {f_ch.translated_title} ... {l_ch.translated_title}"
        )
        flat_items = [it for _i, ch in group for it in ch.items]

        def _on_prog(done_g: int, _tot_g: int, prev: str) -> None:
            if status_callback:
                overall = processed_so_far + done_g
                status_callback(overall, total_paragraphs, f"{ch_label} ({overall}/{total_paragraphs} parágrafos)", prev)

        translated_texts = translate_paragraphs_batch(
            [it.text for it in flat_items],
            target_lang,
            source_lang,
            cache_db,
            cancel_check=cancel_check,
            progress_callback=_on_prog,
            detected_lang_sink=detected_sink,
        )
        cancelled_now = bool(cancel_check and cancel_check())
        for item, trans in zip(flat_items, translated_texts):
            if not cancelled_now or cache_db.get(item.text, source_lang, target_lang) is not None:
                item.translated_text = trans
        processed_so_far += len(flat_items)
        if cancelled_now:
            was_cancelled = True
            break

    book.detected_source_lang = detected_sink[0] if detected_sink else (source_lang if source_lang != "auto" else "en")
    eff_src = book.detected_source_lang

    if was_cancelled:
        partial = _build_partial_book(book)
        if partial.chapters:
            export_book_any(partial, make_partial_output_path(output_path), output_format, target_lang, eff_src, bilingual, opts.include_back_to_toc)
    else:
        export_book_any(book, output_path, output_format, target_lang, eff_src, bilingual, opts.include_back_to_toc)
    return book
