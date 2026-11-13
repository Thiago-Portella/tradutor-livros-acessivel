"""
Orquestrador de Tradução e Aprimoramento de Livros (wxPython + CLI)
otimizado para acessibilidade com NVDA e ElevenReader.

- Aba 1: Traduzir Livro (com motor Google Translate do Absolute Translate, cache SQLite por parágrafo
  e todas as opções de aprimoramento estrutural e textual integradas)
- Aba 2: Apenas Aprimorar / Converter Livro (para livros já em português ou no idioma desejado,
  executando normalização de letras, reconstrução de frases/parágrafos, limpeza de cabeçalhos,
  tratamento de notas de rodapé e organização de sumário instantaneamente sem usar a API)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import sys
import threading
import time
import winsound
from typing import Callable, Optional

from epub_builder import SUPPORTED_FORMATS, export_book
from extractor import BookStructure, EnhancementOptions, extract_book
from translator import (
    LANGUAGES,
    TranslationCacheDB,
    TranslationError,
    TranslationRateLimitError,
    google_translate,
    translate_paragraphs_batch,
)

FOOTNOTE_MODES = {
    "move_end": "Mover notas de rodapé para o fim do capítulo (Recomendado)",
    "remove": "Remover notas de rodapé completamente",
    "keep": "Manter notas de rodapé onde estão",
}


def get_default_cache_path(input_file: str) -> str:
    """
    Retorna o caminho do banco SQLite de progresso garantindo que nunca ultrapasse o limite
    MAX_PATH (260 caracteres) do Windows mesmo com arquivos de nomes muito longos (200+ chars),
    pois o SQLite cria arquivos auxiliares '-journal' / '-wal' ao lado do banco.
    """
    abs_input = os.path.abspath(input_file)
    base_dir = os.path.dirname(abs_input)
    base_name = os.path.splitext(os.path.basename(abs_input))[0]

    # Verifica se já existe um arquivo de cache legado válido (e curto o suficiente para o SQLite)
    legacy_cache = os.path.join(base_dir, f".{base_name}_translation_cache.sqlite3")
    try:
        if os.path.exists(legacy_cache):
            if os.path.getsize(legacy_cache) == 0:
                os.remove(legacy_cache)
            elif len(legacy_cache) <= 215:
                return legacy_cache
    except OSError:
        pass

    short_hash = hashlib.sha256(abs_input.lower().encode("utf-8")).hexdigest()[:12]
    safe_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", base_name).strip("_")[:36] or "livro"

    fallback_dir = os.path.join(os.path.expanduser("~"), ".tradutor_livros_cache")
    os.makedirs(fallback_dir, exist_ok=True)
    return os.path.join(fallback_dir, f"{safe_prefix}_{short_hash}_cache.sqlite3")


def _clamp_output_path_length(dir_path: str, base_name: str, ext: str, suffix: str = "") -> str:
    """Garante que o caminho final de saída nunca exceda 230 caracteres no Windows."""
    max_total = 230
    avail = max(25, max_total - len(dir_path) - 1 - len(suffix) - len(ext))
    trimmed_base = base_name[:avail].rstrip(" ._-") if len(base_name) > avail else base_name
    return os.path.join(dir_path, f"{trimmed_base}{suffix}{ext}")


def get_default_output_path(
    input_file: str,
    target_lang: str = "pt",
    output_format: str = "epub",
    bilingual: bool = False,
    enhance_only: bool = False,
) -> str:
    abs_input = os.path.abspath(input_file)
    base_dir = os.path.dirname(abs_input)
    base_name = os.path.splitext(os.path.basename(abs_input))[0]
    fmt_key = output_format.lower().lstrip(".")
    if fmt_key == "markdown":
        fmt_key = "md"
    ext = SUPPORTED_FORMATS.get(fmt_key, ("", f".{fmt_key}"))[1]

    docs_dir = os.path.join(os.path.expanduser("~"), "Documents", "Livros_Processados")
    candidate = _clamp_output_path_length(base_dir, base_name, ext)

    # Nunca sobrescreve o próprio arquivo de entrada (ex.: traduzir .epub para .epub na mesma pasta)
    if os.path.abspath(candidate).lower() == abs_input.lower():
        try:
            os.makedirs(docs_dir, exist_ok=True)
            docs_candidate = _clamp_output_path_length(docs_dir, base_name, ext)
            if os.path.abspath(docs_candidate).lower() != abs_input.lower():
                return docs_candidate
            suffix = "_aprimorado" if enhance_only else f"_{target_lang}"
            return _clamp_output_path_length(docs_dir, base_name, ext, suffix=suffix)
        except OSError:
            suffix = "_aprimorado" if enhance_only else f"_{target_lang}"
            return _clamp_output_path_length(base_dir, base_name, ext, suffix=suffix)

    probe_file = os.path.join(base_dir, f".write_test_{os.getpid()}")
    try:
        with open(probe_file, "w"):
            pass
        os.remove(probe_file)
        return candidate
    except OSError:
        try:
            os.makedirs(docs_dir, exist_ok=True)
            return _clamp_output_path_length(docs_dir, base_name, ext)
        except OSError:
            local_dir = os.path.dirname(os.path.abspath(__file__))
            return _clamp_output_path_length(local_dir, base_name, ext)


def _ensure_safe_output_path(
    input_path: str,
    output_path: str,
    output_format: str = "epub",
    target_lang: str = "pt",
    enhance_only: bool = False,
) -> str:
    """
    Garante que o caminho de saída escolhido não sobrescreva o arquivo original de entrada
    durante a tradução/aprimoramento e não exceda o limite MAX_PATH do Windows.
    """
    abs_in = os.path.abspath(input_path)
    abs_out = os.path.abspath(output_path)
    out_dir = os.path.dirname(abs_out)
    out_base, out_ext = os.path.splitext(os.path.basename(abs_out))
    if not out_ext:
        fmt_key = output_format.lower().lstrip(".")
        if fmt_key == "markdown":
            fmt_key = "md"
        out_ext = SUPPORTED_FORMATS.get(fmt_key, ("", f".{fmt_key}"))[1]

    if abs_out.lower() == abs_in.lower():
        return get_default_output_path(
            input_path,
            target_lang=target_lang,
            output_format=output_format,
            enhance_only=enhance_only,
        )
    if len(abs_out) > 235:
        return _clamp_output_path_length(out_dir, out_base, out_ext)
    return abs_out


def _describe_toc_method(method: str) -> str:
    method_descriptions = {
        "embedded_toc": "Sumário original embutido no PDF",
        "heuristic_typography": "Algoritmo tipográfico (capítulos descobertos pelo layout/fontes)",
        "printed_toc_parser": "Algoritmo leitor de página de Sumário impressa",
        "smart_page_chunks": "Divisão automática inteligente por blocos de páginas",
        "epub_spine": "Estrutura de capítulos do EPUB",
        "heuristic_txt": "Detecção automática de títulos de capítulos no texto",
        "auto_segmented_txt": "Segmentação automática em capítulos para texto contínuo",
        "single_section": "Seção única contínua",
    }
    return method_descriptions.get(method, method)


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
    """
    Executa apenas os aprimoramentos estruturais e textuais (sem traduzir) e exporta para o formato escolhido.
    Ideal para livros que já estão em português.
    """
    opts = options or EnhancementOptions()
    output_path = _ensure_safe_output_path(
        input_path,
        output_path,
        output_format=output_format,
        target_lang=doc_lang,
        enhance_only=True,
    )
    if status_callback:
        status_callback(10, 100, "Extraindo páginas e aplicando aprimoramentos no livro...", "")

    book = extract_book(
        input_path,
        options=opts,
        start_page=start_page,
        end_page=end_page,
    )

    total_paragraphs = sum(len(ch.items) for ch in book.chapters)
    if total_paragraphs == 0:
        raise TranslationError(
            "Nenhum texto selecionável foi encontrado no arquivo. "
            "Este PDF parece ser composto apenas por imagens escaneadas (sem camada de texto/OCR)."
        )

    toc_desc = _describe_toc_method(book.toc_discovery_method)
    if status_callback:
        status_callback(
            60,
            100,
            f"Estrutura organizada: {len(book.chapters)} capítulos ({toc_desc}). Gerando {output_format.upper()}...",
            f"Capítulos: {len(book.chapters)} | Parágrafos processados: {total_paragraphs} | Método: {toc_desc}",
        )

    export_book(
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
    """
    Executa todo o fluxo de aprimoramento + tradução com cache SQLite imediato por parágrafo.
    Se o livro já tiver sido traduzido antes e o usuário mudar apenas opções de aprimoramento ou formato,
    reaproveita o cache SQLite instantaneamente.
    """
    opts = options or EnhancementOptions()
    output_path = _ensure_safe_output_path(
        input_path,
        output_path,
        output_format=output_format,
        target_lang=target_lang,
        enhance_only=False,
    )
    if status_callback:
        status_callback(0, 100, "Extraindo estrutura, descobrindo capítulos e limpando parágrafos...", "")

    book = extract_book(
        input_path,
        options=opts,
        start_page=start_page,
        end_page=end_page,
    )

    toc_desc = _describe_toc_method(book.toc_discovery_method)
    if status_callback:
        status_callback(
            0,
            100,
            f"Estrutura identificada: {len(book.chapters)} capítulos ({toc_desc})",
            f"Método de sumário: {toc_desc} ({len(book.chapters)} capítulos encontrados)",
        )

    cache_path = get_default_cache_path(input_path)
    cache_db = TranslationCacheDB(cache_path)

    if book.title:
        cached_book_title = cache_db.get(book.title, source_lang, target_lang)
        if cached_book_title:
            book.title = cached_book_title
        else:
            try:
                t_title, _ = google_translate(book.title, target_lang, source_lang)
                if t_title:
                    cache_db.put(book.title, t_title, source_lang, target_lang)
                    book.title = t_title
            except Exception:
                pass

    total_paragraphs = sum(len(ch.items) for ch in book.chapters)
    if total_paragraphs == 0:
        raise TranslationError(
            "Nenhum texto selecionável foi encontrado no arquivo. "
            "Este PDF parece ser composto apenas por imagens escaneadas (sem camada de texto/OCR)."
        )

    # Traduz todos os títulos de capítulos em lote para máxima velocidade (especialmente em livros com 50-100 seções)
    raw_ch_titles = [ch.title for ch in book.chapters]
    try:
        translated_ch_titles = translate_paragraphs_batch(
            raw_ch_titles,
            target_lang=target_lang,
            source_lang=source_lang,
            cache_db=cache_db,
            cancel_check=cancel_check,
        )
        for ch, t_ch in zip(book.chapters, translated_ch_titles):
            ch.translated_title = t_ch or ch.title
    except Exception:
        for ch in book.chapters:
            ch.translated_title = ch.title

    # Agrupa capítulos muito curtos (ex: livros enciclopédicos com 100 tópicos de 3 parágrafos)
    # em lotes de ~25 parágrafos para reduzir requisições HTTP em até 10x
    chapter_groups: List[List[Tuple[int, Chapter]]] = []
    current_group: List[Tuple[int, Chapter]] = []
    current_group_items = 0
    for ch_idx, chapter in enumerate(book.chapters, start=1):
        current_group.append((ch_idx, chapter))
        current_group_items += len(chapter.items)
        if current_group_items >= 20:
            chapter_groups.append(current_group)
            current_group = []
            current_group_items = 0
    if current_group:
        chapter_groups.append(current_group)

    processed_so_far = 0

    for group in chapter_groups:
        if cancel_check and cancel_check():
            break

        first_idx, first_ch = group[0]
        last_idx, last_ch = group[-1]
        if len(group) == 1:
            ch_label = f"Capítulo {first_idx}/{len(book.chapters)}: {first_ch.translated_title}"
        else:
            ch_label = (
                f"Capítulos {first_idx} a {last_idx}/{len(book.chapters)}: "
                f"{first_ch.translated_title} ... {last_ch.translated_title}"
            )

        flat_items = [item for _idx, ch in group for item in ch.items]
        orig_texts = [item.text for item in flat_items]

        def _on_group_progress(done_in_grp: int, _total_in_grp: int, preview: str) -> None:
            overall_done = processed_so_far + done_in_grp
            if status_callback:
                status_callback(
                    overall_done,
                    total_paragraphs,
                    f"{ch_label} ({overall_done}/{total_paragraphs} parágrafos)",
                    preview,
                )

        translated_texts = translate_paragraphs_batch(
            orig_texts,
            target_lang=target_lang,
            source_lang=source_lang,
            cache_db=cache_db,
            cancel_check=cancel_check,
            progress_callback=_on_group_progress,
        )

        for item, trans in zip(flat_items, translated_texts):
            item.translated_text = trans

        processed_so_far += len(flat_items)

        export_book(
            book=book,
            output_path=output_path,
            fmt=output_format,
            target_lang=target_lang,
            source_lang=source_lang if source_lang != "auto" else "en",
            bilingual=bilingual,
            include_back_to_toc=opts.include_back_to_toc,
        )

    return book


# =====================================================================
# INTERFACE DE LINHA DE COMANDO (CLI)
# =====================================================================
def run_cli(args: argparse.Namespace) -> int:
    input_path = os.path.abspath(args.input)
    if not os.path.exists(input_path):
        print(f"Erro: Arquivo não encontrado: {input_path}", file=sys.stderr)
        return 1

    fmt = args.format.lower().lstrip(".")
    if fmt == "markdown":
        fmt = "md"

    output_path = (
        os.path.abspath(args.output)
        if args.output
        else get_default_output_path(
            input_path,
            args.target_lang,
            fmt,
            bilingual=args.bilingual,
            enhance_only=args.enhance_only,
        )
    )

    opts = EnhancementOptions(
        normalize_chars=not args.no_normalize,
        reflow_sentences=not args.no_reflow,
        remove_headers_footers=not args.no_remove_headers,
        organize_toc=not args.no_organize_toc,
        force_heuristic_toc=args.force_discover_toc,
        footnote_mode=args.footnotes,
        include_back_to_toc=args.back_to_toc,
    )

    print(f"Arquivo de entrada: {input_path}")
    print(f"Modo: {'Apenas Aprimoramento / Conversão' if args.enhance_only else f'Tradução ({args.source_lang} -> {args.target_lang})'}")
    print(f"Formato escolhido: {fmt.upper()} -> {output_path}")

    last_pct = -1

    def _cli_status(done: int, total: int, status_msg: str, preview: str) -> None:
        nonlocal last_pct
        pct = int((done / total) * 100) if total > 0 else 0
        if pct != last_pct or done == total or done == 0:
            last_pct = pct
            print(f"[{pct:3d}%] {status_msg}", flush=True)

    start_time = time.monotonic()
    try:
        if args.enhance_only:
            enhance_only_book_pipeline(
                input_path=input_path,
                output_path=output_path,
                output_format=fmt,
                doc_lang=args.target_lang,
                options=opts,
                start_page=args.start_page,
                end_page=args.end_page,
                status_callback=_cli_status,
            )
        else:
            translate_book_pipeline(
                input_path=input_path,
                output_path=output_path,
                output_format=fmt,
                source_lang=args.source_lang,
                target_lang=args.target_lang,
                bilingual=args.bilingual,
                options=opts,
                start_page=args.start_page,
                end_page=args.end_page,
                status_callback=_cli_status,
            )
        elapsed = time.monotonic() - start_time
        print(f"\nConcluído com sucesso em {elapsed:.1f}s!")
        print(f"Arquivo ({fmt.upper()}) salvo em: {output_path}")
        return 0
    except KeyboardInterrupt:
        print("\nOperação pausada pelo usuário. Todo o progresso foi salvo.")
        return 130
    except Exception as e:
        print(f"\nErro: {e}", file=sys.stderr)
        return 1


# =====================================================================
# INTERFACE GRÁFICA ACESSÍVEL COM 2 ABAS (wxPython) PARA NVDA
# =====================================================================
def run_gui(initial_file: Optional[str] = None) -> int:
    import wx

    class BookWorkflowTab(wx.Panel):
        """
        Painel reutilizável para cada aba do wx.Notebook:
        - translate_mode=True  -> Aba 1: Traduzir Livro (+ Aprimoramentos)
        - translate_mode=False -> Aba 2: Apenas Aprimorar / Converter Livro (sem traduzir)
        """

        def __init__(self, parent: wx.Window, frame: wx.Frame, translate_mode: bool = True, default_file: Optional[str] = None):
            super().__init__(parent)
            self.frame = frame
            self.translate_mode = translate_mode
            self._worker_thread: Optional[threading.Thread] = None
            self._cancel_requested = False
            self._is_running = False

            main_sizer = wx.BoxSizer(wx.VERTICAL)

            # 1. Seleção de Arquivo e Formato de Saída
            file_box = wx.StaticBoxSizer(
                wx.VERTICAL,
                self,
                "1. Seleção do Livro e Formato de Saída",
            )
            file_row = wx.BoxSizer(wx.HORIZONTAL)
            lbl_in = wx.StaticText(self, label="&Arquivo do livro:")
            self.txt_input = wx.TextCtrl(self)
            if default_file and os.path.exists(default_file):
                self.txt_input.SetValue(default_file)
            self.btn_browse_in = wx.Button(self, label="Procurar &Livro...")
            self.btn_browse_in.Bind(wx.EVT_BUTTON, self._on_browse_input)

            file_row.Add(lbl_in, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            file_row.Add(self.txt_input, 1, wx.EXPAND | wx.RIGHT, 8)
            file_row.Add(self.btn_browse_in, 0)
            file_box.Add(file_row, 0, wx.EXPAND | wx.ALL, 5)

            fmt_row = wx.BoxSizer(wx.HORIZONTAL)
            lbl_fmt = wx.StaticText(self, label="&Formato de saída:")
            self._fmt_keys = list(SUPPORTED_FORMATS.keys())
            self._fmt_labels = [SUPPORTED_FORMATS[k][0] for k in self._fmt_keys]
            self.cmb_format = wx.Choice(self, choices=self._fmt_labels)
            self.cmb_format.SetSelection(0)  # EPUB por padrão
            self.cmb_format.Bind(wx.EVT_CHOICE, lambda e: self._update_default_output_path())

            fmt_row.Add(lbl_fmt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            fmt_row.Add(self.cmb_format, 1, wx.EXPAND)
            file_box.Add(fmt_row, 0, wx.EXPAND | wx.ALL, 5)

            out_row = wx.BoxSizer(wx.HORIZONTAL)
            lbl_out = wx.StaticText(self, label="&Salvar arquivo em:")
            self.txt_output = wx.TextCtrl(self)
            self.btn_browse_out = wx.Button(self, label="Escolher &Destino...")
            self.btn_browse_out.Bind(wx.EVT_BUTTON, self._on_browse_output)

            out_row.Add(lbl_out, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            out_row.Add(self.txt_output, 1, wx.EXPAND | wx.RIGHT, 8)
            out_row.Add(self.btn_browse_out, 0)
            file_box.Add(out_row, 0, wx.EXPAND | wx.ALL, 5)

            main_sizer.Add(file_box, 0, wx.EXPAND | wx.ALL, 8)

            # 2. Se for Aba de Tradução, mostra Idiomas e Modo Bilíngue
            self._lang_codes = list(LANGUAGES.keys())
            self._lang_names = [f"{name} ({code})" for code, name in LANGUAGES.items()]
            tgt_codes = [c for c in self._lang_codes if c != "auto"]
            tgt_names = [f"{LANGUAGES[c]} ({c})" for c in tgt_codes]
            self._tgt_codes = tgt_codes

            if self.translate_mode:
                lang_box = wx.StaticBoxSizer(wx.VERTICAL, self, "2. Idiomas de Tradução")
                lang_row = wx.BoxSizer(wx.HORIZONTAL)

                lbl_src = wx.StaticText(self, label="Idioma de &Origem:")
                self.cmb_source = wx.Choice(self, choices=self._lang_names)
                self.cmb_source.SetSelection(self._lang_codes.index("auto"))

                lbl_tgt = wx.StaticText(self, label="Idioma de &Destino:")
                self.cmb_target = wx.Choice(self, choices=tgt_names)
                if "pt" in tgt_codes:
                    self.cmb_target.SetSelection(tgt_codes.index("pt"))
                self.cmb_target.Bind(wx.EVT_CHOICE, lambda e: self._update_default_output_path())

                lang_row.Add(lbl_src, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
                lang_row.Add(self.cmb_source, 1, wx.RIGHT, 14)
                lang_row.Add(lbl_tgt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
                lang_row.Add(self.cmb_target, 1)
                lang_box.Add(lang_row, 0, wx.EXPAND | wx.ALL, 5)

                self.chk_bilingual = wx.CheckBox(
                    self,
                    label="Modo &Bilíngue (exibir parágrafo original acima do parágrafo traduzido)",
                )
                self.chk_bilingual.SetValue(False)
                self.chk_bilingual.Bind(wx.EVT_CHECKBOX, lambda e: self._update_default_output_path())
                lang_box.Add(self.chk_bilingual, 0, wx.ALL, 4)

                main_sizer.Add(lang_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
            else:
                self.cmb_source = None
                self.cmb_target = None
                self.chk_bilingual = None

            # 3. Opções Granulares de Aprimoramento e Estrutura
            enh_title = (
                "3. Opções de Aprimoramento e Sumário"
                if self.translate_mode
                else "2. Aprimoramentos de Texto, Frases e Sumário (Para Livros já no Idioma Desejado)"
            )
            enh_box = wx.StaticBoxSizer(wx.VERTICAL, self, enh_title)

            self.chk_normalize_chars = wx.CheckBox(
                self,
                label="&Normalizar letras e caracteres (corrigir ligaturas como ﬁ/ﬀ, espaços múltiplos e hifens invisíveis)",
            )
            self.chk_normalize_chars.SetValue(True)

            self.chk_reflow_sentences = wx.CheckBox(
                self,
                label="&Reconstruir fim de frases e parágrafos (juntar palavras hifenizadas e unir frases quebradas entre linhas/páginas)",
            )
            self.chk_reflow_sentences.SetValue(True)

            self.chk_remove_headers = wx.CheckBox(
                self,
                label="Remover &cabeçalhos repetitivos e números de página soltos (evita interrupções no NVDA e ElevenReader)",
            )
            self.chk_remove_headers.SetValue(True)

            self.chk_organize_toc = wx.CheckBox(
                self,
                label="Organizar por &Sumário e Capítulos (descobrir capítulos automaticamente se não existirem)",
            )
            self.chk_organize_toc.SetValue(True)

            self.chk_force_heuristic_toc = wx.CheckBox(
                self,
                label="Forçar recriação do sumário pelo algoritmo &visual (ignorar sumário original do PDF)",
            )
            self.chk_force_heuristic_toc.SetValue(False)

            self.chk_back_to_toc = wx.CheckBox(
                self,
                label="Adicionar link '[&Voltar ao Sumário]' no final de cada capítulo (desmarcado por padrão para leitura contínua)",
            )
            self.chk_back_to_toc.SetValue(False)

            self.chk_sound_beeps = wx.CheckBox(
                self,
                label="Emitir bipes &sonoros discretos durante o processamento e ao concluir",
            )
            self.chk_sound_beeps.SetValue(True)

            # Caixa de seleção para Notas de Rodapé
            fn_row = wx.BoxSizer(wx.HORIZONTAL)
            lbl_fn = wx.StaticText(self, label="Notas de &rodapé na base da página:")
            self._fn_keys = list(FOOTNOTE_MODES.keys())
            self._fn_labels = [FOOTNOTE_MODES[k] for k in self._fn_keys]
            self.cmb_footnotes = wx.Choice(self, choices=self._fn_labels)
            self.cmb_footnotes.SetSelection(0)  # move_end por padrão

            fn_row.Add(lbl_fn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            fn_row.Add(self.cmb_footnotes, 1, wx.EXPAND)

            enh_box.Add(self.chk_normalize_chars, 0, wx.ALL, 3)
            enh_box.Add(self.chk_reflow_sentences, 0, wx.ALL, 3)
            enh_box.Add(self.chk_remove_headers, 0, wx.ALL, 3)
            enh_box.Add(self.chk_organize_toc, 0, wx.ALL, 3)
            enh_box.Add(self.chk_force_heuristic_toc, 0, wx.ALL, 3)
            enh_box.Add(self.chk_back_to_toc, 0, wx.ALL, 3)
            enh_box.Add(self.chk_sound_beeps, 0, wx.ALL, 3)
            enh_box.Add(fn_row, 0, wx.EXPAND | wx.ALL, 5)

            # Intervalo de páginas e botão de testar descoberta de sumário
            page_row = wx.BoxSizer(wx.HORIZONTAL)
            lbl_pstart = wx.StaticText(self, label="Página &Inicial (vazio = início):")
            self.txt_start_page = wx.TextCtrl(self, size=(60, -1))
            lbl_pend = wx.StaticText(self, label="Página &Final (vazio = fim):")
            self.txt_end_page = wx.TextCtrl(self, size=(60, -1))
            self.btn_preview_toc = wx.Button(
                self, label="Testar &Descoberta de Sumário (Alt+D)"
            )
            self.btn_preview_toc.Bind(wx.EVT_BUTTON, self._on_preview_toc)

            page_row.Add(lbl_pstart, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            page_row.Add(self.txt_start_page, 0, wx.RIGHT, 12)
            page_row.Add(lbl_pend, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            page_row.Add(self.txt_end_page, 0, wx.RIGHT, 12)
            page_row.Add(self.btn_preview_toc, 1, wx.EXPAND)
            enh_box.Add(page_row, 0, wx.EXPAND | wx.ALL, 5)

            main_sizer.Add(enh_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

            # 4. Progresso e Log
            prog_box = wx.StaticBoxSizer(wx.VERTICAL, self, "Progresso e Histórico")
            self.lbl_status = wx.StaticText(
                self,
                label="Pronto. Selecione um livro para começar.",
            )
            self.gauge = wx.Gauge(self, range=100)

            lbl_log = wx.StaticText(
                self, label="&Histórico, sumário detectado e prévia (somente leitura):"
            )
            self.txt_log = wx.TextCtrl(
                self,
                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
            )

            prog_box.Add(self.lbl_status, 0, wx.EXPAND | wx.ALL, 5)
            prog_box.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
            prog_box.Add(lbl_log, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
            prog_box.Add(self.txt_log, 1, wx.EXPAND | wx.ALL, 5)

            main_sizer.Add(prog_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

            # 5. Botões de Ação
            btn_row = wx.BoxSizer(wx.HORIZONTAL)
            start_lbl = (
                "&Iniciar / Retomar Tradução (Alt+I)"
                if self.translate_mode
                else "&Iniciar Aprimoramento / Conversão (Alt+I)"
            )
            self.btn_start = wx.Button(self, label=start_lbl)
            self.btn_start.Bind(wx.EVT_BUTTON, self._on_start)

            self.btn_pause = wx.Button(self, label="&Pausar (Alt+P)")
            self.btn_pause.Bind(wx.EVT_BUTTON, self._on_pause)
            self.btn_pause.Enable(False)

            self.btn_open_folder = wx.Button(self, label="Abrir &Pasta de Saída (Alt+A)")
            self.btn_open_folder.Bind(wx.EVT_BUTTON, self._on_open_folder)

            self.btn_close = wx.Button(self, label="Fec&har (Esc)")
            self.btn_close.Bind(wx.EVT_BUTTON, lambda e: self.frame.Close())

            btn_row.Add(self.btn_start, 0, wx.RIGHT, 8)
            btn_row.Add(self.btn_pause, 0, wx.RIGHT, 8)
            btn_row.Add(self.btn_open_folder, 0, wx.RIGHT, 8)
            btn_row.Add(self.btn_close, 0)

            main_sizer.Add(btn_row, 0, wx.ALIGN_CENTER | wx.BOTTOM, 8)

            self.SetSizer(main_sizer)
            self._update_default_output_path()
            self.txt_input.Bind(wx.EVT_TEXT, lambda e: self._update_default_output_path())

        def _get_selected_format_key(self) -> str:
            idx = self.cmb_format.GetSelection()
            return self._fmt_keys[idx] if idx != wx.NOT_FOUND else "epub"

        def _get_selected_source_lang(self) -> str:
            if not self.cmb_source:
                return "auto"
            idx = self.cmb_source.GetSelection()
            return self._lang_codes[idx] if idx != wx.NOT_FOUND else "auto"

        def _get_selected_target_lang(self) -> str:
            if not self.cmb_target:
                return "pt"
            idx = self.cmb_target.GetSelection()
            return self._tgt_codes[idx] if idx != wx.NOT_FOUND else "pt"

        def _build_enhancement_options(self) -> EnhancementOptions:
            fn_idx = self.cmb_footnotes.GetSelection()
            fn_mode = self._fn_keys[fn_idx] if fn_idx != wx.NOT_FOUND else "move_end"
            return EnhancementOptions(
                normalize_chars=self.chk_normalize_chars.GetValue(),
                reflow_sentences=self.chk_reflow_sentences.GetValue(),
                remove_headers_footers=self.chk_remove_headers.GetValue(),
                organize_toc=self.chk_organize_toc.GetValue(),
                force_heuristic_toc=self.chk_force_heuristic_toc.GetValue(),
                footnote_mode=fn_mode,
                include_back_to_toc=self.chk_back_to_toc.GetValue(),
            )

        def _update_default_output_path(self) -> None:
            in_path = self.txt_input.GetValue().strip()
            if in_path:
                bilingual = self.chk_bilingual.GetValue() if self.chk_bilingual else False
                out_path = get_default_output_path(
                    in_path,
                    self._get_selected_target_lang(),
                    self._get_selected_format_key(),
                    bilingual=bilingual,
                    enhance_only=not self.translate_mode,
                )
                self.txt_output.SetValue(out_path)

        def _on_browse_input(self, _event: wx.Event) -> None:
            wildcard = (
                "Livros suportados (*.pdf;*.epub;*.txt;*.md)|*.pdf;*.epub;*.txt;*.md|"
                "Arquivos PDF (*.pdf)|*.pdf|"
                "Arquivos EPUB (*.epub)|*.epub|"
                "Arquivos de Texto (*.txt;*.md)|*.txt;*.md|"
                "Todos os arquivos (*.*)|*.*"
            )
            with wx.FileDialog(
                self,
                "Selecionar Livro",
                wildcard=wildcard,
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
            ) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    self.txt_input.SetValue(dlg.GetPath())
                    self._update_default_output_path()

        def _on_browse_output(self, _event: wx.Event) -> None:
            fmt_key = self._get_selected_format_key()
            label, ext = SUPPORTED_FORMATS[fmt_key]
            wildcard = f"{label}|*{ext}|Todos os arquivos (*.*)|*.*"

            in_path = self.txt_input.GetValue().strip()
            out_path = self.txt_output.GetValue().strip()
            default_dir = ""
            default_file = ""

            if in_path:
                orig_base = os.path.splitext(os.path.basename(in_path))[0]
                default_file = f"{orig_base}{ext}"
                if out_path:
                    out_dir = os.path.dirname(os.path.abspath(out_path))
                    if os.path.isdir(out_dir):
                        default_dir = out_dir
                if not default_dir:
                    in_dir = os.path.dirname(os.path.abspath(in_path))
                    if os.path.isdir(in_dir):
                        default_dir = in_dir
            elif out_path:
                out_base = os.path.splitext(os.path.basename(out_path))[0]
                default_file = f"{out_base}{ext}"
                out_dir = os.path.dirname(os.path.abspath(out_path))
                if os.path.isdir(out_dir):
                    default_dir = out_dir

            with wx.FileDialog(
                self,
                "Salvar Livro Processado",
                defaultDir=default_dir,
                defaultFile=default_file,
                wildcard=wildcard,
                style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            ) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    self.txt_output.SetValue(dlg.GetPath())

        def _append_log(self, message: str) -> None:
            self.txt_log.AppendText(message + "\n")

        def _parse_page_bounds(self) -> Optional[tuple[Optional[int], Optional[int]]]:
            p_start: Optional[int] = None
            p_end: Optional[int] = None
            raw_start = self.txt_start_page.GetValue().strip()
            raw_end = self.txt_end_page.GetValue().strip()
            if raw_start:
                try:
                    p_start = int(raw_start)
                except ValueError:
                    wx.MessageBox("A página inicial deve ser um número inteiro.", "Aviso")
                    return None
            if raw_end:
                try:
                    p_end = int(raw_end)
                except ValueError:
                    wx.MessageBox("A página final deve ser um número inteiro.", "Aviso")
                    return None
            return p_start, p_end

        def _on_preview_toc(self, _event: wx.Event) -> None:
            in_path = self.txt_input.GetValue().strip()
            if not in_path or not os.path.exists(in_path):
                wx.MessageBox("Selecione um arquivo de livro válido primeiro.", "Aviso")
                return
            bounds = self._parse_page_bounds()
            if bounds is None:
                return
            p_start, p_end = bounds
            opts = self._build_enhancement_options()

            self.lbl_status.SetLabel("Analisando páginas e descobrindo sumário...")
            try:
                book = extract_book(
                    in_path,
                    options=opts,
                    start_page=p_start,
                    end_page=p_end,
                )
                self._append_log("=" * 60)
                self._append_log(
                    f"Sumário Descoberto para '{book.title}' ({_describe_toc_method(book.toc_discovery_method)}):"
                )
                if not book.chapters:
                    msg_scan = (
                        "  [AVISO] Nenhum texto selecionável encontrado nas páginas deste arquivo.\n"
                        "  Este PDF é composto apenas por imagens escaneadas (sem camada de texto/OCR)."
                    )
                    self._append_log(msg_scan)
                    self._append_log("=" * 60)
                    self.lbl_status.SetLabel("PDF escaneado sem camada de texto selecionável (OCR).")
                    wx.MessageBox(
                        "Este arquivo PDF contém apenas imagens escaneadas e não possui camada de texto selecionável (OCR).\n\n"
                        "Para extrair capítulos, aprimorar ou traduzir, utilize um PDF que possua texto selecionável.",
                        "PDF Escaneado (Sem Camada de Texto)",
                        wx.OK | wx.ICON_WARNING,
                    )
                    return

                for ch in book.chapters:
                    fn_count = sum(1 for it in ch.items if it.kind == "footnote")
                    fn_info = f", {fn_count} notas" if fn_count else ""
                    self._append_log(
                        f"  Cap. {ch.index:02d}: {ch.title} (Páginas {ch.start_page}-{ch.end_page}, {len(ch.items)} itens{fn_info})"
                    )
                self._append_log("=" * 60)
                self.lbl_status.SetLabel(
                    f"Descoberta concluída: {len(book.chapters)} capítulos listados no campo de Histórico."
                )
                self.txt_log.SetFocus()
            except Exception as e:
                wx.MessageBox(f"Erro ao inspecionar capítulos: {e}", "Erro")

        def _on_start(self, _event: wx.Event) -> None:
            if self._is_running:
                return

            in_path = self.txt_input.GetValue().strip()
            out_path = self.txt_output.GetValue().strip()
            if not in_path or not os.path.exists(in_path):
                wx.MessageBox(
                    "Por favor, selecione um arquivo de livro válido.",
                    "Arquivo não encontrado",
                    wx.OK | wx.ICON_WARNING,
                )
                self.txt_input.SetFocus()
                return

            if not out_path:
                self._update_default_output_path()
                out_path = self.txt_output.GetValue().strip()

            bounds = self._parse_page_bounds()
            if bounds is None:
                return
            p_start, p_end = bounds

            fmt_key = self._get_selected_format_key()
            source_lang = self._get_selected_source_lang()
            target_lang = self._get_selected_target_lang()
            bilingual = self.chk_bilingual.GetValue() if self.chk_bilingual else False
            opts = self._build_enhancement_options()
            play_beeps = self.chk_sound_beeps.GetValue()

            self._is_running = True
            self._cancel_requested = False
            self.btn_start.Enable(False)
            self.btn_pause.Enable(True)
            self.btn_pause.SetFocus()

            action_name = "tradução" if self.translate_mode else "aprimoramento"
            self._append_log(
                f"Iniciando {action_name} de '{os.path.basename(in_path)}' para {fmt_key.upper()}..."
            )

            def _worker() -> None:
                last_chapter_prefix = ""
                try:
                    def _status_cb(done: int, total: int, status_text: str, preview: str) -> None:
                        nonlocal last_chapter_prefix
                        pct = int((done / total) * 100) if total > 0 else 0
                        ch_prefix = status_text.split("(")[0].strip()
                        is_new_chapter = ch_prefix != last_chapter_prefix
                        if is_new_chapter:
                            last_chapter_prefix = ch_prefix
                            if play_beeps and done > 0 and self.translate_mode:
                                winsound.Beep(520, 70)

                        wx.CallAfter(
                            self._update_ui_progress,
                            pct,
                            status_text,
                            preview if is_new_chapter or done % 15 == 0 or done == total else "",
                        )

                    if self.translate_mode:
                        translate_book_pipeline(
                            input_path=in_path,
                            output_path=out_path,
                            output_format=fmt_key,
                            source_lang=source_lang,
                            target_lang=target_lang,
                            bilingual=bilingual,
                            options=opts,
                            start_page=p_start,
                            end_page=p_end,
                            cancel_check=lambda: self._cancel_requested,
                            status_callback=_status_cb,
                        )
                    else:
                        enhance_only_book_pipeline(
                            input_path=in_path,
                            output_path=out_path,
                            output_format=fmt_key,
                            doc_lang="pt",
                            options=opts,
                            start_page=p_start,
                            end_page=p_end,
                            status_callback=_status_cb,
                        )

                    if self._cancel_requested:
                        if play_beeps:
                            winsound.Beep(300, 200)
                        wx.CallAfter(
                            self._on_worker_finished,
                            f"Operação pausada. Arquivo parcial ({fmt_key.upper()}) disponível em: {out_path}",
                        )
                    else:
                        if play_beeps:
                            winsound.Beep(660, 120)
                            winsound.Beep(880, 180)
                        wx.CallAfter(
                            self._on_worker_finished,
                            f"Concluído com 100% de sucesso! Arquivo ({fmt_key.upper()}) gerado em: {out_path}",
                        )
                except TranslationRateLimitError as e:
                    if play_beeps:
                        winsound.Beep(220, 400)
                    wx.CallAfter(
                        self._on_worker_finished,
                        f"Limite temporário da API atingido ({e}). Progresso salvo! Clique em Iniciar/Retomar em instantes.",
                    )
                except Exception as e:
                    if play_beeps:
                        winsound.Beep(220, 400)
                    wx.CallAfter(
                        self._on_worker_finished,
                        f"Erro: {e}. Todo o progresso anterior continua salvo.",
                    )

            self._worker_thread = threading.Thread(target=_worker, daemon=True)
            self._worker_thread.start()

        def _update_ui_progress(self, pct: int, status_text: str, preview: str) -> None:
            self.gauge.SetValue(max(0, min(100, pct)))
            self.lbl_status.SetLabel(f"[{pct}%] {status_text}")
            if preview:
                self._append_log(f"[{pct}%] {status_text} -> {preview}")

        def _on_worker_finished(self, final_message: str) -> None:
            self._is_running = False
            self.btn_start.Enable(True)
            self.btn_pause.Enable(False)
            self.btn_start.SetFocus()
            self.lbl_status.SetLabel(final_message)
            self._append_log(final_message)

        def _on_pause(self, _event: wx.Event) -> None:
            if self._is_running:
                self._cancel_requested = True
                self.lbl_status.SetLabel("Pausando após concluir o lote atual e salvando arquivo parcial...")
                self.btn_pause.Enable(False)

        def _on_open_folder(self, _event: wx.Event) -> None:
            out_path = self.txt_output.GetValue().strip()
            folder = os.path.dirname(os.path.abspath(out_path)) if out_path else os.getcwd()
            if os.path.exists(folder):
                os.startfile(folder)

        def cancel_if_running(self) -> None:
            if self._is_running:
                self._cancel_requested = True

    class BookProcessorFrame(wx.Frame):
        def __init__(self, initial_path: Optional[str] = None):
            super().__init__(
                None,
                title="Tradutor e Aprimorador Acessível de Livros",
                size=(860, 740),
            )
            panel = wx.Panel(self)
            root_sizer = wx.BoxSizer(wx.VERTICAL)

            self.notebook = wx.Notebook(panel)
            self.tab_translate = BookWorkflowTab(
                self.notebook, self, translate_mode=True, default_file=initial_path
            )
            self.tab_enhance = BookWorkflowTab(
                self.notebook, self, translate_mode=False, default_file=initial_path
            )

            self.notebook.AddPage(self.tab_translate, "1. Traduzir Livro")
            self.notebook.AddPage(self.tab_enhance, "2. Apenas Aprimorar / Converter Livro")

            root_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 6)
            panel.SetSizer(root_sizer)

            self.Bind(wx.EVT_CLOSE, self._on_close_window)
            self.Center()

        def _on_close_window(self, event: wx.CloseEvent) -> None:
            self.tab_translate.cancel_if_running()
            self.tab_enhance.cancel_if_running()
            event.Skip()

    app = wx.App(False)
    frame = BookProcessorFrame(initial_path=initial_file)
    frame.Show()
    app.MainLoop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tradutor e Aprimorador Completo de Livros (EPUB, PDF, HTML, Markdown, TXT)"
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="Caminho do livro de entrada (.pdf, .epub, .txt, .md). Se omitido ou com --gui, abre a interface gráfica.",
    )
    parser.add_argument("-o", "--output", help="Caminho do arquivo de saída")
    parser.add_argument(
        "-f",
        "--format",
        default="epub",
        choices=["epub", "pdf", "html", "md", "markdown", "txt"],
        help="Formato do arquivo de saída: epub, pdf, html, md, txt (padrão: epub)",
    )
    parser.add_argument(
        "--enhance-only",
        action="store_true",
        help="Executa apenas os aprimoramentos de texto, frases e sumário sem traduzir (ideal para livros já em português)",
    )
    parser.add_argument("-s", "--source-lang", default="auto", help="Idioma de origem (padrão: auto)")
    parser.add_argument("-t", "--target-lang", default="pt", help="Idioma de destino (padrão: pt)")
    parser.add_argument(
        "-b",
        "--bilingual",
        action="store_true",
        help="Gera edição bilíngue (parágrafo original + parágrafo traduzido)",
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Desativa a normalização de letras e ligaturas tipográficas",
    )
    parser.add_argument(
        "--no-reflow",
        action="store_true",
        help="Desativa a reconstrução de fim de frases e união de parágrafos entre linhas/páginas",
    )
    parser.add_argument(
        "--no-remove-headers",
        action="store_true",
        help="Desativa a remoção de cabeçalhos repetitivos e números de página soltos",
    )
    parser.add_argument(
        "--no-organize-toc",
        action="store_true",
        help="Desativa a organização e descoberta automática de capítulos/sumário",
    )
    parser.add_argument(
        "--force-discover-toc",
        action="store_true",
        help="Força o algoritmo visual/heurístico a descobrir capítulos mesmo se o PDF já tiver TOC embutido",
    )
    parser.add_argument(
        "--footnotes",
        default="move_end",
        choices=["move_end", "remove", "keep"],
        help="Tratamento de notas de rodapé: move_end (padrão), remove ou keep",
    )
    parser.add_argument(
        "--back-to-toc",
        action="store_true",
        help="Adiciona o link '[Voltar ao Sumário]' no final de cada capítulo (desativado por padrão)",
    )
    parser.add_argument("--start-page", type=int, help="Página inicial (base 1)")
    parser.add_argument("--end-page", type=int, help="Página final (base 1)")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Executa diretamente no terminal (sem abrir a interface gráfica wxPython)",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Abre a interface gráfica acessível em wxPython",
    )

    args = parser.parse_args()
    if args.cli and args.input:
        return run_cli(args)

    initial = args.input if (args.input and os.path.exists(args.input)) else None
    return run_gui(initial_file=initial)


if __name__ == "__main__":
    sys.exit(main())
