# Role: controller
"""Menu Ajuda acessível ao NVDA, checagem silenciosa na abertura e diálogos de atualização."""

from __future__ import annotations

import sys
import threading
import webbrowser
from typing import Optional

import wx

from src.domain.update_models import DevelopmentModeUpdateError, ReleaseManifest, UpdateCheckResult
from src.domain.version import APP_NAME, APP_VERSION, GITHUB_REPO, RELEASES_PAGE_URL
from src.services.self_update_service import (
    check_for_updates,
    prepare_and_stage_update,
    trigger_update_and_exit_ready,
)


class UpdatePromptDialog(wx.Dialog):
    """Diálogo acessível exibindo versão disponível e notas de lançamento somente leitura."""

    def __init__(self, parent: wx.Window, manifest: ReleaseManifest):
        super().__init__(parent, title=f"Atualização Disponível: v{manifest.version}", size=(560, 400))
        sizer = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(
            self,
            label=(
                f"Uma nova versão do {APP_NAME} está disponível.\n"
                f"Versão instalada: v{APP_VERSION}  |  Nova versão: v{manifest.version}"
            ),
        )
        lbl_notes = wx.StaticText(self, label="&Notas da versão:")
        notes_text = manifest.release_notes.strip() or "Melhorias gerais e correções de estabilidade."
        self.txt_notes = wx.TextCtrl(
            self,
            value=notes_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        action_label = (
            "&Atualizar Agora"
            if getattr(sys, "frozen", False)
            else "&Abrir Página de Releases no Navegador"
        )
        self.btn_update = wx.Button(self, wx.ID_OK, label=action_label)
        self.btn_later = wx.Button(self, wx.ID_CANCEL, label="&Depois (Esc)")
        self.btn_update.SetDefault()
        btn_row.Add(self.btn_update, 0, wx.RIGHT, 8)
        btn_row.Add(self.btn_later, 0)

        sizer.Add(intro, 0, wx.EXPAND | wx.ALL, 10)
        sizer.Add(lbl_notes, 0, wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.txt_notes, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(btn_row, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(sizer)
        self.SetEscapeId(wx.ID_CANCEL)
        self.CenterOnParent()
        self.btn_update.SetFocus()


def _is_frame_busy(frame: wx.Frame) -> bool:
    t_busy = getattr(getattr(frame, "tab_translate", None), "_is_running", False)
    e_busy = getattr(getattr(frame, "tab_enhance", None), "_is_running", False)
    return bool(t_busy or e_busy)


def _run_download_and_apply(frame: wx.Frame, manifest: ReleaseManifest) -> None:
    dlg = wx.ProgressDialog(
        "Baixando Atualização",
        f"Baixando v{manifest.version} do GitHub Releases...",
        maximum=100,
        parent=frame,
        style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_AUTO_HIDE | wx.PD_ELAPSED_TIME,
    )
    cancel_flag = threading.Event()
    result_box: dict[str, object] = {}

    def _on_progress(downloaded: int, total: int) -> None:
        pct = min(99, int((downloaded * 100) / total)) if total > 0 else 50
        def _upd() -> None:
            if not dlg:
                return
            keep_going, _ = dlg.Update(pct, f"Baixando v{manifest.version}... {pct}%")
            if not keep_going:
                cancel_flag.set()
        wx.CallAfter(_upd)

    def _worker() -> None:
        try:
            staged = prepare_and_stage_update(
                manifest,
                progress_callback=_on_progress,
                cancel_check=cancel_flag.is_set,
            )
            result_box["staged"] = staged
        except Exception as exc:
            result_box["error"] = exc
        finally:
            wx.CallAfter(_finish)

    def _finish() -> None:
        if dlg:
            dlg.Destroy()
        if not frame or frame.IsBeingDeleted():
            return
        err = result_box.get("error")
        if isinstance(err, DevelopmentModeUpdateError):
            wx.MessageBox(str(err), "Modo Desenvolvimento", wx.OK | wx.ICON_INFORMATION, parent=frame)
            return
        if isinstance(err, Exception):
            wx.MessageBox(f"Não foi possível atualizar:\n{err}", "Erro na Atualização", wx.OK | wx.ICON_ERROR, parent=frame)
            return
        staged = result_box.get("staged")
        if staged is not None:
            try:
                trigger_update_and_exit_ready(staged, relaunch=True)
            except Exception as launch_exc:
                wx.MessageBox(
                    f"Não foi possível iniciar o instalador de atualização:\n{launch_exc}",
                    "Erro na Atualização",
                    wx.OK | wx.ICON_ERROR,
                    parent=frame,
                )
                return
            frame.Close()

    threading.Thread(target=_worker, daemon=True).start()


def _handle_check_result(frame: wx.Frame, result: UpdateCheckResult, manual: bool) -> None:
    if not frame or frame.IsBeingDeleted():
        return
    if result.error_message:
        if manual:
            wx.MessageBox(
                f"Não foi possível verificar atualizações:\n{result.error_message}",
                "Verificar Atualizações",
                wx.OK | wx.ICON_WARNING,
                parent=frame,
            )
        return
    if not result.update_available or result.manifest is None:
        if manual:
            wx.MessageBox(
                f"Você já está utilizando a versão mais recente (v{result.current_version}).",
                "Sem Atualizações",
                wx.OK | wx.ICON_INFORMATION,
                parent=frame,
            )
        return
    if _is_frame_busy(frame):
        if manual:
            wx.MessageBox(
                "Aguarde o processamento atual terminar ou pause antes de aplicar uma atualização.",
                "Processamento em Andamento",
                wx.OK | wx.ICON_INFORMATION,
                parent=frame,
            )
        return

    with UpdatePromptDialog(frame, result.manifest) as prompt:
        if prompt.ShowModal() != wx.ID_OK:
            return
    if not getattr(sys, "frozen", False):
        webbrowser.open(RELEASES_PAGE_URL)
        return
    _run_download_and_apply(frame, result.manifest)


def trigger_update_check(frame: wx.Frame, manual: bool = True) -> None:
    """Dispara checagem de versão em thread secundária e notifica a UI com segurança."""
    def _worker() -> None:
        res = check_for_updates()
        wx.CallAfter(_handle_check_result, frame, res, manual)

    threading.Thread(target=_worker, daemon=True).start()


def show_about_dialog(frame: wx.Frame) -> None:
    """Exibe informações acessíveis de versão e repositório oficial."""
    wx.MessageBox(
        f"{APP_NAME}\nVersão instalada: v{APP_VERSION}\n\n"
        f"Repositório oficial no GitHub:\nhttps://github.com/{GITHUB_REPO}",
        "Sobre o Tradutor de Livros",
        wx.OK | wx.ICON_INFORMATION,
        parent=frame,
    )


def attach_help_menu_and_startup_check(frame: wx.Frame, enable_startup_check: bool = True) -> None:
    """Anexa barra de menu Ajuda acessível (F5 / Sobre) e agenda checagem silenciosa."""
    menubar = wx.MenuBar()
    help_menu = wx.Menu()
    item_check = help_menu.Append(wx.ID_ANY, "&Verificar Atualizações...\tF5")
    help_menu.AppendSeparator()
    item_about = help_menu.Append(wx.ID_ABOUT, "&Sobre o Tradutor de Livros...")
    menubar.Append(help_menu, "A&juda")
    frame.SetMenuBar(menubar)

    frame.Bind(wx.EVT_MENU, lambda _evt: trigger_update_check(frame, manual=True), item_check)
    frame.Bind(wx.EVT_MENU, lambda _evt: show_about_dialog(frame), item_about)
    if enable_startup_check:
        frame._startup_update_timer = wx.CallLater(1500, lambda: trigger_update_check(frame, manual=False))
