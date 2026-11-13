# Role: controller
"""Construção dos controles wxPython acessíveis sem colisão de mnemônicos Alt."""

from __future__ import annotations

import os
from typing import Optional

import wx

from src.domain.models import FOOTNOTE_MODES, SUPPORTED_FORMATS
from src.policies.i18n_labels import LANGUAGES


def build_tab_controls(panel: wx.Panel, translate_mode: bool, default_file: Optional[str]) -> None:
    """Cria e organiza os controles acessíveis no painel com aceleradores Alt exclusivos."""
    main_sizer = wx.BoxSizer(wx.VERTICAL)

    # 1. Seleção de Arquivo e Formato
    file_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "1. Seleção do Livro e Formato de Saída")
    f_box = file_box.GetStaticBox()
    file_row = wx.BoxSizer(wx.HORIZONTAL)
    lbl_in = wx.StaticText(f_box, label="&Arquivo do livro:")
    panel.txt_input = wx.TextCtrl(f_box)
    if default_file and os.path.exists(default_file):
        panel.txt_input.SetValue(default_file)
    panel.btn_browse_in = wx.Button(f_box, label="Procurar &Livro...")
    file_row.Add(lbl_in, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    file_row.Add(panel.txt_input, 1, wx.EXPAND | wx.RIGHT, 8)
    file_row.Add(panel.btn_browse_in, 0)
    file_box.Add(file_row, 0, wx.EXPAND | wx.ALL, 5)

    fmt_row = wx.BoxSizer(wx.HORIZONTAL)
    lbl_fmt = wx.StaticText(f_box, label="&Formato de saída:")
    panel._fmt_keys = list(SUPPORTED_FORMATS.keys())
    panel.cmb_format = wx.Choice(f_box, choices=[SUPPORTED_FORMATS[k][0] for k in panel._fmt_keys])
    panel.cmb_format.SetSelection(0)
    fmt_row.Add(lbl_fmt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    fmt_row.Add(panel.cmb_format, 1, wx.EXPAND)
    file_box.Add(fmt_row, 0, wx.EXPAND | wx.ALL, 5)

    out_row = wx.BoxSizer(wx.HORIZONTAL)
    lbl_out = wx.StaticText(f_box, label="Salvar &em:")
    panel.txt_output = wx.TextCtrl(f_box)
    panel.btn_browse_out = wx.Button(f_box, label="Escolher Destin&o...")
    out_row.Add(lbl_out, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    out_row.Add(panel.txt_output, 1, wx.EXPAND | wx.RIGHT, 8)
    out_row.Add(panel.btn_browse_out, 0)
    file_box.Add(out_row, 0, wx.EXPAND | wx.ALL, 5)
    main_sizer.Add(file_box, 0, wx.EXPAND | wx.ALL, 8)

    # 2. Idiomas (Tradução na Aba 1, ou Idioma do Livro na Aba 2)
    panel._lang_codes = list(LANGUAGES.keys())
    panel._lang_names = [f"{name} ({code})" for code, name in LANGUAGES.items()]
    panel._tgt_codes = [c for c in panel._lang_codes if c != "auto"]
    tgt_names = [f"{LANGUAGES[c]} ({c})" for c in panel._tgt_codes]

    if translate_mode:
        lang_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "2. Idiomas de Tradução")
        l_box = lang_box.GetStaticBox()
        lang_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_src = wx.StaticText(l_box, label="Idioma de O&rigem:")
        panel.cmb_source = wx.Choice(l_box, choices=panel._lang_names)
        panel.cmb_source.SetSelection(panel._lang_codes.index("auto"))
        lbl_tgt = wx.StaticText(l_box, label="Idioma de &Destino:")
        panel.cmb_target = wx.Choice(l_box, choices=tgt_names)
        if "pt" in panel._tgt_codes:
            panel.cmb_target.SetSelection(panel._tgt_codes.index("pt"))
        lang_row.Add(lbl_src, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        lang_row.Add(panel.cmb_source, 1, wx.RIGHT, 14)
        lang_row.Add(lbl_tgt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        lang_row.Add(panel.cmb_target, 1)
        lang_box.Add(lang_row, 0, wx.EXPAND | wx.ALL, 5)

        panel.chk_bilingual = wx.CheckBox(
            l_box, label="Modo &Bilíngue (exibir parágrafo original acima do traduzido)"
        )
        panel.chk_bilingual.SetValue(False)
        lang_box.Add(panel.chk_bilingual, 0, wx.ALL, 4)
        panel.cmb_doc_lang = None
        main_sizer.Add(lang_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
    else:
        lang_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "2. Idioma do Livro (Metadados e NVDA)")
        l_box = lang_box.GetStaticBox()
        doc_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_doc = wx.StaticText(l_box, label="Idio&ma do Livro:")
        panel.cmb_doc_lang = wx.Choice(l_box, choices=tgt_names)
        if "pt" in panel._tgt_codes:
            panel.cmb_doc_lang.SetSelection(panel._tgt_codes.index("pt"))
        doc_row.Add(lbl_doc, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        doc_row.Add(panel.cmb_doc_lang, 1, wx.EXPAND)
        lang_box.Add(doc_row, 0, wx.EXPAND | wx.ALL, 5)
        panel.cmb_source = None
        panel.cmb_target = None
        panel.chk_bilingual = None
        main_sizer.Add(lang_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

    # 3. Opções de Aprimoramento e Sumário (letras & exclusivas)
    enh_title = "3. Opções de Aprimoramento e Sumário" if translate_mode else "3. Aprimoramentos de Texto, Frases e Sumário"
    enh_box = wx.StaticBoxSizer(wx.VERTICAL, panel, enh_title)
    e_box = enh_box.GetStaticBox()
    panel.chk_normalize_chars = wx.CheckBox(e_box, label="&Normalizar letras e ligaturas (ﬁ/ﬀ, espaços múltiplos e hifens invisíveis)")
    panel.chk_normalize_chars.SetValue(True)
    panel.chk_reflow_sentences = wx.CheckBox(e_box, label="Re&construir frases e parágrafos quebrados entre linhas ou páginas")
    panel.chk_reflow_sentences.SetValue(True)
    panel.chk_remove_headers = wx.CheckBox(e_box, label="Remover cabe&çalhos repetitivos e números de página soltos")
    panel.chk_remove_headers.SetValue(True)
    panel.chk_organize_toc = wx.CheckBox(e_box, label="Organizar por &Sumário e Capítulos automaticamente")
    panel.chk_organize_toc.SetValue(True)
    panel.chk_force_heuristic_toc = wx.CheckBox(e_box, label="Forçar algoritmo &visual de descoberta de sumário (ignorar TOC embutido)")
    panel.chk_force_heuristic_toc.SetValue(False)
    panel.chk_back_to_toc = wx.CheckBox(e_box, label="Adicionar lin&k '[Voltar ao Sumário]' no final de cada capítulo")
    panel.chk_back_to_toc.SetValue(False)
    panel.chk_sound_beeps = wx.CheckBox(e_box, label="Emitir bipes a&uditivos discretos durante o processamento")
    panel.chk_sound_beeps.SetValue(True)

    fn_row = wx.BoxSizer(wx.HORIZONTAL)
    lbl_fn = wx.StaticText(e_box, label="No&tas de rodapé:")
    panel._fn_keys = list(FOOTNOTE_MODES.keys())
    panel.cmb_footnotes = wx.Choice(e_box, choices=[FOOTNOTE_MODES[k] for k in panel._fn_keys])
    panel.cmb_footnotes.SetSelection(0)
    fn_row.Add(lbl_fn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    fn_row.Add(panel.cmb_footnotes, 1, wx.EXPAND)

    for chk in (
        panel.chk_normalize_chars, panel.chk_reflow_sentences, panel.chk_remove_headers,
        panel.chk_organize_toc, panel.chk_force_heuristic_toc, panel.chk_back_to_toc,
        panel.chk_sound_beeps,
    ):
        enh_box.Add(chk, 0, wx.ALL, 3)
    enh_box.Add(fn_row, 0, wx.EXPAND | wx.ALL, 5)

    page_row = wx.BoxSizer(wx.HORIZONTAL)
    lbl_pstart = wx.StaticText(e_box, label="Página Inicial (&1 = início):")
    panel.txt_start_page = wx.TextCtrl(e_box, size=(60, -1))
    lbl_pend = wx.StaticText(e_box, label="Página Final (va&zio = fim):")
    panel.txt_end_page = wx.TextCtrl(e_box, size=(60, -1))
    panel.btn_preview_toc = wx.Button(e_box, label="Testar Descoberta de Sumário (&W)")
    page_row.Add(lbl_pstart, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
    page_row.Add(panel.txt_start_page, 0, wx.RIGHT, 12)
    page_row.Add(lbl_pend, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
    page_row.Add(panel.txt_end_page, 0, wx.RIGHT, 12)
    page_row.Add(panel.btn_preview_toc, 1, wx.EXPAND)
    enh_box.Add(page_row, 0, wx.EXPAND | wx.ALL, 5)
    main_sizer.Add(enh_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

    # 4. Progresso e Histórico
    prog_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Progresso e Histórico")
    p_box = prog_box.GetStaticBox()
    panel.lbl_status = wx.StaticText(p_box, label="Pronto. Selecione um livro para começar.")
    panel.gauge = wx.Gauge(p_box, range=100)
    lbl_log = wx.StaticText(p_box, label="&Histórico, sumário detectado e prévia (somente leitura):")
    panel.txt_log = wx.TextCtrl(p_box, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
    prog_box.Add(panel.lbl_status, 0, wx.EXPAND | wx.ALL, 5)
    prog_box.Add(panel.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
    prog_box.Add(lbl_log, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
    prog_box.Add(panel.txt_log, 1, wx.EXPAND | wx.ALL, 5)
    main_sizer.Add(prog_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

    # 5. Botões de Ação (sem colisão de mnemônicos)
    btn_row = wx.BoxSizer(wx.HORIZONTAL)
    start_lbl = "&Iniciar / Retomar Tradução (Alt+I)" if translate_mode else "&Iniciar Aprimoramento / Conversão (Alt+I)"
    panel.btn_start = wx.Button(panel, label=start_lbl)
    panel.btn_pause = wx.Button(panel, label="&Pausar (Alt+P)")
    panel.btn_pause.Enable(False)
    panel.btn_open_folder = wx.Button(panel, label="Abrir Pasta de Saída (&G)")
    panel.btn_close = wx.Button(panel, label="Fechar (&X / Esc)")
    btn_row.Add(panel.btn_start, 0, wx.RIGHT, 8)
    btn_row.Add(panel.btn_pause, 0, wx.RIGHT, 8)
    btn_row.Add(panel.btn_open_folder, 0, wx.RIGHT, 8)
    btn_row.Add(panel.btn_close, 0)
    main_sizer.Add(btn_row, 0, wx.ALIGN_CENTER | wx.BOTTOM, 8)

    panel.SetSizer(main_sizer)
