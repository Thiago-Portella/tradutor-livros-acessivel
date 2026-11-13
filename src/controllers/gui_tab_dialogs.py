# Role: controller
"""Ações auxiliares de diálogos de arquivo e formatação de prévia de sumário."""

from __future__ import annotations

import os
from typing import Optional

import wx

from src.domain.models import BookStructure, SUPPORTED_FORMATS
from src.policies.i18n_labels import describe_toc_method
from src.policies.path_policy import validate_page_bounds


def choose_input_book(panel: wx.Panel) -> Optional[str]:
    wildcard = (
        "Livros suportados (*.pdf;*.epub;*.txt;*.md)|*.pdf;*.epub;*.txt;*.md|"
        "Arquivos PDF (*.pdf)|*.pdf|Arquivos EPUB (*.epub)|*.epub|"
        "Arquivos de Texto (*.txt;*.md)|*.txt;*.md|Todos os arquivos (*.*)|*.*"
    )
    with wx.FileDialog(panel, "Selecionar Livro", wildcard=wildcard, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
        if dlg.ShowModal() == wx.ID_OK:
            return dlg.GetPath()
    return None


def choose_output_book(panel: wx.Panel, fmt_key: str, in_path: str, out_path: str) -> Optional[str]:
    label, ext = SUPPORTED_FORMATS[fmt_key]
    default_dir, default_file = "", ""
    if in_path:
        default_file = f"{os.path.splitext(os.path.basename(in_path))[0]}{ext}"
        if out_path and os.path.isdir(os.path.dirname(os.path.abspath(out_path))):
            default_dir = os.path.dirname(os.path.abspath(out_path))
        elif os.path.isdir(os.path.dirname(os.path.abspath(in_path))):
            default_dir = os.path.dirname(os.path.abspath(in_path))
    with wx.FileDialog(
        panel,
        "Salvar Livro Processado",
        defaultDir=default_dir,
        defaultFile=default_file,
        wildcard=f"{label}|*{ext}|Todos os arquivos (*.*)|*.*",
        style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
    ) as dlg:
        if dlg.ShowModal() == wx.ID_OK:
            return dlg.GetPath()
    return None


def parse_tab_page_bounds(raw_start: str, raw_end: str) -> Optional[tuple[Optional[int], Optional[int]]]:
    p_start = p_end = None
    try:
        if raw_start.strip():
            p_start = int(raw_start.strip())
        if raw_end.strip():
            p_end = int(raw_end.strip())
        validate_page_bounds(p_start, p_end)
    except ValueError as e:
        wx.MessageBox(str(e), "Intervalo de Páginas Inválido", wx.OK | wx.ICON_WARNING)
        return None
    return p_start, p_end


def render_toc_preview_to_tab(tab: wx.Panel, book: Optional[BookStructure], err: Optional[Exception]) -> None:
    if not tab or not tab.btn_preview_toc:
        return
    tab.btn_preview_toc.Enable(True)
    tab.btn_start.Enable(True)
    if err is not None:
        tab.lbl_status.SetLabel("Falha ao analisar sumário.")
        wx.MessageBox(f"Erro ao inspecionar capítulos: {err}", "Erro")
        return
    assert book is not None
    tab._append_log("=" * 60)
    tab._append_log(f"Sumário Descoberto para '{book.title}' ({describe_toc_method(book.toc_discovery_method)}):")
    if not book.chapters:
        tab._append_log("  [AVISO] Nenhum texto selecionável encontrado nas páginas deste arquivo.")
        tab._append_log("=" * 60)
        tab.lbl_status.SetLabel("PDF escaneado sem camada de texto selecionável (OCR).")
        wx.MessageBox("Este arquivo não possui texto selecionável.", "PDF Escaneado", wx.OK | wx.ICON_WARNING)
        return
    for ch in book.chapters:
        fn_cnt = sum(1 for it in ch.items if it.kind == "footnote")
        fn_info = f", {fn_cnt} notas" if fn_cnt else ""
        tab._append_log(f"  Cap. {ch.index:02d}: {ch.title} (Páginas {ch.start_page}-{ch.end_page}, {len(ch.items)} itens{fn_info})")
    tab._append_log("=" * 60)
    tab.lbl_status.SetLabel(f"Descoberta concluída: {len(book.chapters)} capítulos listados no Histórico.")
    tab.txt_log.SetFocus()
