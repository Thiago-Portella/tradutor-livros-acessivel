# Role: controller
"""Janela principal acessível wxPython com atalho Esc e fechamento cooperativo."""

from __future__ import annotations

from typing import Optional

import wx

from src.controllers.gui_update_dialog import (
    attach_help_menu_and_startup_check,
    open_help_manual_from_gui,
)
from src.controllers.gui_workflow_tab import BookWorkflowTab
from src.domain.version import APP_NAME, APP_VERSION


class BookProcessorFrame(wx.Frame):
    """Frame principal com duas abas acessíveis ao NVDA."""

    def __init__(self, initial_path: Optional[str] = None, enable_startup_update_check: bool = True):
        super().__init__(
            None,
            title=f"{APP_NAME} v{APP_VERSION}",
            size=(880, 760),
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
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        attach_help_menu_and_startup_check(self, enable_startup_check=enable_startup_update_check)
        self.Center()

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_F1:
            open_help_manual_from_gui(self)
            return
        if code == wx.WXK_ESCAPE and wx.GetActiveWindow() is self:
            if not self.tab_translate._is_running and not self.tab_enhance._is_running:
                self.Close()
                return
        event.Skip()

    def _on_close_window(self, event: wx.CloseEvent) -> None:
        timer = getattr(self, "_startup_update_timer", None)
        if timer is not None and timer.IsRunning():
            timer.Stop()
        self.tab_translate.cancel_and_wait(timeout_sec=2.5)
        self.tab_enhance.cancel_and_wait(timeout_sec=2.5)
        event.Skip()


def run_gui(initial_file: Optional[str] = None) -> int:
    app = wx.App(False)
    frame = BookProcessorFrame(initial_path=initial_file)
    frame.Show()
    app.MainLoop()
    return 0
