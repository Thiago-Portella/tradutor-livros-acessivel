# Role: controller
"""Painel reutilizável de aba da GUI com preview assíncrono e controle seguro de threads."""

from __future__ import annotations

import os
import threading
import winsound
from typing import Optional

import wx

from src.controllers.gui_controls_builder import build_tab_controls
from src.controllers.gui_tab_dialogs import (
    choose_input_book,
    choose_output_book,
    parse_tab_page_bounds,
    render_toc_preview_to_tab,
)
from src.domain.models import EnhancementOptions, TranslationRateLimitError
from src.policies.path_policy import get_default_output_path, make_partial_output_path
from src.services.book_io_dispatch import extract_book_any
from src.services.book_pipeline import enhance_only_book_pipeline, translate_book_pipeline


class BookWorkflowTab(wx.Panel):
    """Painel de aba para Traduzir Livro ou Apenas Aprimorar / Converter Livro."""

    def __init__(self, parent: wx.Window, frame: wx.Frame, translate_mode: bool = True, default_file: Optional[str] = None):
        super().__init__(parent)
        self.frame = frame
        self.translate_mode = translate_mode
        self._worker_thread: Optional[threading.Thread] = None
        self._preview_thread: Optional[threading.Thread] = None
        self._cancel_requested = False
        self._is_running = False

        build_tab_controls(self, translate_mode, default_file)

        self.btn_browse_in.Bind(wx.EVT_BUTTON, self._on_browse_input)
        self.btn_browse_out.Bind(wx.EVT_BUTTON, self._on_browse_output)
        self.cmb_format.Bind(wx.EVT_CHOICE, lambda _e: self._update_default_output_path())
        self.txt_input.Bind(wx.EVT_TEXT, lambda _e: self._update_default_output_path())
        if self.cmb_target:
            self.cmb_target.Bind(wx.EVT_CHOICE, lambda _e: self._update_default_output_path())
        if self.chk_bilingual:
            self.chk_bilingual.Bind(wx.EVT_CHECKBOX, lambda _e: self._update_default_output_path())
        if self.cmb_doc_lang:
            self.cmb_doc_lang.Bind(wx.EVT_CHOICE, lambda _e: self._update_default_output_path())
        self.btn_preview_toc.Bind(wx.EVT_BUTTON, self._on_preview_toc)
        self.btn_start.Bind(wx.EVT_BUTTON, self._on_start)
        self.btn_pause.Bind(wx.EVT_BUTTON, self._on_pause)
        self.btn_open_folder.Bind(wx.EVT_BUTTON, self._on_open_folder)
        self.btn_close.Bind(wx.EVT_BUTTON, lambda _e: self.frame.Close())
        self._update_default_output_path()

    def _get_selected_format_key(self) -> str:
        idx = self.cmb_format.GetSelection()
        return self._fmt_keys[idx] if idx != wx.NOT_FOUND else "epub"

    def _get_selected_source_lang(self) -> str:
        if not self.cmb_source:
            return "auto"
        idx = self.cmb_source.GetSelection()
        return self._lang_codes[idx] if idx != wx.NOT_FOUND else "auto"

    def _get_selected_target_lang(self) -> str:
        choice = self.cmb_target if self.translate_mode else self.cmb_doc_lang
        if not choice:
            return "pt"
        idx = choice.GetSelection()
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
            self.txt_output.SetValue(
                get_default_output_path(
                    in_path,
                    self._get_selected_target_lang(),
                    self._get_selected_format_key(),
                    bilingual=bilingual,
                    enhance_only=not self.translate_mode,
                )
            )

    def _on_browse_input(self, _event: wx.Event) -> None:
        chosen = choose_input_book(self)
        if chosen:
            self.txt_input.SetValue(chosen)
            self._update_default_output_path()

    def _on_browse_output(self, _event: wx.Event) -> None:
        chosen = choose_output_book(
            self, self._get_selected_format_key(), self.txt_input.GetValue().strip(), self.txt_output.GetValue().strip()
        )
        if chosen:
            self.txt_output.SetValue(chosen)

    def _append_log(self, message: str) -> None:
        self.txt_log.AppendText(message + "\n")

    def _on_preview_toc(self, _event: wx.Event) -> None:
        if self._is_running or (self._preview_thread and self._preview_thread.is_alive()):
            return
        in_path = self.txt_input.GetValue().strip()
        if not in_path or not os.path.exists(in_path):
            wx.MessageBox("Selecione um arquivo de livro válido primeiro.", "Aviso")
            return
        bounds = parse_tab_page_bounds(self.txt_start_page.GetValue(), self.txt_end_page.GetValue())
        if bounds is None:
            return
        p_start, p_end = bounds
        opts = self._build_enhancement_options()

        self.btn_preview_toc.Enable(False)
        self.btn_start.Enable(False)
        self.lbl_status.SetLabel("Analisando páginas e descobrindo sumário em segundo plano...")

        def _preview_worker() -> None:
            try:
                book = extract_book_any(in_path, options=opts, start_page=p_start, end_page=p_end)
                wx.CallAfter(render_toc_preview_to_tab, self, book, None)
            except Exception as e:
                wx.CallAfter(render_toc_preview_to_tab, self, None, e)

        self._preview_thread = threading.Thread(target=_preview_worker, daemon=True)
        self._preview_thread.start()

    def _on_start(self, _event: wx.Event) -> None:
        if self._is_running:
            return
        in_path, out_path = self.txt_input.GetValue().strip(), self.txt_output.GetValue().strip()
        if not in_path or not os.path.exists(in_path):
            wx.MessageBox("Por favor, selecione um arquivo de livro válido.", "Arquivo não encontrado", wx.OK | wx.ICON_WARNING)
            self.txt_input.SetFocus()
            return
        if not out_path:
            self._update_default_output_path()
            out_path = self.txt_output.GetValue().strip()
        bounds = parse_tab_page_bounds(self.txt_start_page.GetValue(), self.txt_end_page.GetValue())
        if bounds is None:
            return
        p_start, p_end = bounds
        fmt_key = self._get_selected_format_key()
        source_lang, target_lang = self._get_selected_source_lang(), self._get_selected_target_lang()
        bilingual = self.chk_bilingual.GetValue() if self.chk_bilingual else False
        opts, play_beeps = self._build_enhancement_options(), self.chk_sound_beeps.GetValue()

        self._is_running, self._cancel_requested = True, False
        self.btn_start.Enable(False)
        self.btn_preview_toc.Enable(False)
        self.btn_pause.Enable(True)
        self.btn_pause.SetFocus()
        self._append_log(f"Iniciando {'tradução' if self.translate_mode else 'aprimoramento'} de '{os.path.basename(in_path)}' para {fmt_key.upper()}...")

        def _worker() -> None:
            last_ch_prefix = ""
            try:
                def _cb(done: int, total: int, status_text: str, preview: str) -> None:
                    nonlocal last_ch_prefix
                    pct = int((done / total) * 100) if total > 0 else 0
                    ch_prefix = status_text.split("(")[0].strip()
                    is_new = ch_prefix != last_ch_prefix
                    if is_new:
                        last_ch_prefix = ch_prefix
                        if play_beeps and done > 0 and self.translate_mode:
                            winsound.Beep(520, 70)
                    wx.CallAfter(self._update_ui_progress, pct, status_text, preview if is_new or done % 15 == 0 or done == total else "")

                if self.translate_mode:
                    translate_book_pipeline(in_path, out_path, fmt_key, source_lang, target_lang, bilingual, opts, p_start, p_end, lambda: self._cancel_requested, _cb)
                else:
                    enhance_only_book_pipeline(in_path, out_path, fmt_key, target_lang, opts, p_start, p_end, _cb)

                if self._cancel_requested:
                    if play_beeps:
                        winsound.Beep(300, 200)
                    partial_p = make_partial_output_path(out_path)
                    wx.CallAfter(self._on_worker_finished, f"Operação pausada. Arquivo parcial disponível em: {partial_p}")
                else:
                    if play_beeps:
                        winsound.Beep(660, 120)
                        winsound.Beep(880, 180)
                    wx.CallAfter(self._on_worker_finished, f"Concluído com 100% de sucesso! Arquivo ({fmt_key.upper()}) gerado em: {out_path}")
            except TranslationRateLimitError as e:
                if play_beeps:
                    winsound.Beep(220, 400)
                wx.CallAfter(self._on_worker_finished, f"Limite temporário da API ({e}). Progresso salvo no SQLite! Retome em instantes.")
            except Exception as e:
                if play_beeps:
                    winsound.Beep(220, 400)
                wx.CallAfter(self._on_worker_finished, f"Erro: {e}.")

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
        self.btn_preview_toc.Enable(True)
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

    def cancel_and_wait(self, timeout_sec: float = 2.5) -> None:
        if self._is_running:
            self._cancel_requested = True
        for th in (self._worker_thread, self._preview_thread):
            if th and th.is_alive():
                th.join(timeout=timeout_sec)
