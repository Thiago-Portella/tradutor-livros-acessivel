# Role: policy
"""Testes 1-para-1 do Exemplo Concreto e dos Cenários 1 a 6 do Manual HTML5 (F1)."""

from __future__ import annotations

import gc
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

import wx

import book_translator
from src.controllers.gui_frame import BookProcessorFrame
from src.controllers.gui_update_dialog import open_help_manual_from_gui, show_about_dialog
from src.domain.version import APP_NAME, APP_VERSION
from src.policies.user_manual_content import render_user_manual_html
from src.services.help_manual_service import generate_user_manual_html, open_user_manual


class _ManualHtmlAuditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.html_lang = ""
        self.in_title = False
        self.title_text = ""
        self.landmarks: dict[str, int] = {"header": 0, "nav": 0, "main": 0, "footer": 0}
        self.nav_labels: list[str] = []
        self.headings: list[tuple[int, dict[str, str]]] = []
        self.skip_links: list[dict[str, str]] = []
        self.tables_count = 0
        self.captions_count = 0
        self.th_scopes: list[str] = []
        self.figcaption_ids: set[str] = set()
        self.pre_blocks: list[dict[str, str]] = []
        self.in_pre = False
        self.pre_has_code = False
        self.pre_with_code_count = 0
        self.in_summary = False
        self.headings_inside_summary = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.html_lang = attr_map.get("lang", "")
        elif tag == "title":
            self.in_title = True
        elif tag in self.landmarks:
            self.landmarks[tag] += 1
            if tag == "nav":
                self.nav_labels.append(attr_map.get("aria-label", ""))
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.headings.append((int(tag[1]), attr_map))
            if self.in_summary:
                self.headings_inside_summary += 1
        elif tag == "a" and "skip-link" in attr_map.get("class", ""):
            self.skip_links.append(attr_map)
        elif tag == "table":
            self.tables_count += 1
        elif tag == "caption":
            self.captions_count += 1
        elif tag == "th":
            self.th_scopes.append(attr_map.get("scope", ""))
        elif tag == "figcaption" and attr_map.get("id"):
            self.figcaption_ids.add(attr_map["id"])
        elif tag == "pre":
            self.pre_blocks.append(attr_map)
            self.in_pre = True
            self.pre_has_code = False
        elif tag == "code" and self.in_pre:
            self.pre_has_code = True
        elif tag == "summary":
            self.in_summary = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag == "pre":
            if self.pre_has_code:
                self.pre_with_code_count += 1
            self.in_pre = False
        elif tag == "summary":
            self.in_summary = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_text += data


def _extract_mnemonic_key(label: str) -> str:
    pos = label.find("&")
    if pos != -1 and pos + 1 < len(label) and label[pos + 1] not in (" ", "&"):
        return label[pos + 1].upper()
    return ""


def _collect_window_mnemonics(window: wx.Window) -> list[str]:
    keys: list[str] = []
    if hasattr(window, "GetLabel"):
        key = _extract_mnemonic_key(window.GetLabel())
        if key:
            keys.append(key)
    for child in window.GetChildren():
        keys.extend(_collect_window_mnemonics(child))
    return keys


class BehaviourHelpManualTests(unittest.TestCase):
    def test_00_concrete_usage_example(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "saida", "manual_usuario.html")
            manual_path = generate_user_manual_html(target)
            opened_urls: list[str] = []

            def _opener(url: str) -> bool:
                opened_urls.append(url)
                return True

            opened_path = open_user_manual(output_path=manual_path, browser_opener=_opener)
            self.assertEqual(opened_path, manual_path)
            self.assertTrue(os.path.isfile(manual_path))
            self.assertEqual(len(opened_urls), 1)
            self.assertTrue(opened_urls[0].startswith("file:///"))

    def test_scenario_01_semantic_html5_and_accessibility_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = generate_user_manual_html(os.path.join(tmp, "manual.html"))
            content = Path(out).read_text(encoding="utf-8")

        self.assertTrue(content.startswith("<!DOCTYPE html>"))
        parser = _ManualHtmlAuditParser()
        parser.feed(content)

        self.assertEqual(parser.html_lang, "pt-BR")
        self.assertIn(APP_VERSION, parser.title_text)
        self.assertIn(APP_NAME, parser.title_text)
        self.assertEqual(parser.landmarks, {"header": 1, "nav": 1, "main": 1, "footer": 1})
        self.assertEqual(parser.nav_labels, ["Sumário do Manual"])
        self.assertEqual(len(parser.skip_links), 1)
        self.assertEqual(parser.skip_links[0].get("href"), "#conteudo-principal")

        h1_list = [h for h in parser.headings if h[0] == 1]
        self.assertEqual(len(h1_list), 1)
        self.assertEqual(h1_list[0][1].get("id"), "conteudo-principal")
        self.assertEqual(h1_list[0][1].get("tabindex"), "-1")

        prev_level = 0
        for level, _attrs in parser.headings:
            if prev_level:
                self.assertLessEqual(level, prev_level + 1, f"Salto de nível h{prev_level} para h{level}")
            prev_level = level

        self.assertGreaterEqual(parser.tables_count, 5)
        self.assertEqual(parser.captions_count, parser.tables_count)
        self.assertTrue(all(sc in ("col", "row") for sc in parser.th_scopes))
        self.assertGreaterEqual(len(parser.pre_blocks), 1)
        self.assertEqual(parser.pre_with_code_count, len(parser.pre_blocks))
        for pre_attrs in parser.pre_blocks:
            self.assertEqual(pre_attrs.get("role"), "region")
            self.assertEqual(pre_attrs.get("tabindex"), "0")
            self.assertIn(pre_attrs.get("aria-labelledby"), parser.figcaption_ids)
        self.assertEqual(parser.headings_inside_summary, 0)

    def test_scenario_02_complete_program_documentation_coverage(self) -> None:
        html_doc = render_user_manual_html()
        expected_tokens = (
            "1. Traduzir Livro",
            "2. Apenas Aprimorar / Converter Livro",
            "Modo Bilíngue",
            "Idioma do Livro",
            "F1",
            "F5",
            "Esc",
            "Ctrl",
            "Alt",
            ".epub",
            ".pdf",
            ".html",
            ".md",
            ".txt",
            "move_end",
            "remove",
            "keep",
            "SQLite WAL",
            "_parcial",
            "520 Hz",
            "660 Hz",
            "880 Hz",
            "300 Hz",
            "220 Hz",
            "--cli",
            "--enhance-only",
            "--help-manual",
            "--check-update",
            "--apply-update",
            "HTTP 429",
        )
        for token in expected_tokens:
            self.assertIn(token, html_doc, f"Conteúdo ausente no manual: {token}")

    def test_scenario_03_open_user_manual_invokes_file_uri_in_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "doc", "manual_usuario.html")
            seen: list[str] = []
            returned = open_user_manual(output_path=out_path, browser_opener=lambda uri: seen.append(uri) or True)
            self.assertEqual(returned, os.path.abspath(out_path))
            self.assertTrue(os.path.exists(returned))
            self.assertEqual(seen, [Path(returned).resolve().as_uri()])

    def test_scenario_04_gui_f1_shortcut_and_help_menu_without_mnemonic_collision(self) -> None:
        app = wx.App(False)
        frame = BookProcessorFrame(enable_startup_update_check=False)
        try:
            menu_bar = frame.GetMenuBar()
            self.assertIsNotNone(menu_bar)
            self.assertEqual(menu_bar.GetMenuLabel(0), "A&juda")
            menu_key = _extract_mnemonic_key(menu_bar.GetMenuLabel(0))
            self.assertEqual(menu_key, "J")

            help_menu = menu_bar.GetMenu(0)
            labels = [item.GetItemLabel() for item in help_menu.GetMenuItems() if not item.IsSeparator()]
            self.assertIn("&Manual do Usuário (HTML)...\tF1", labels)
            self.assertIn("&Verificar Atualizações...\tF5", labels)
            item_keys = [_extract_mnemonic_key(lbl) for lbl in labels if _extract_mnemonic_key(lbl)]
            self.assertEqual(len(item_keys), len(set(item_keys)), f"Colisão interna no menu Ajuda: {labels}")
            for tab in (frame.tab_translate, frame.tab_enhance):
                tab_keys = _collect_window_mnemonics(tab)
                self.assertNotIn(menu_key, tab_keys, f"Colisão de Alt+{menu_key} entre menu e aba")

            fake_f1 = mock.MagicMock()
            fake_f1.GetKeyCode.return_value = wx.WXK_F1
            with mock.patch("src.controllers.gui_frame.open_help_manual_from_gui", return_value="ok.html") as mock_open:
                frame._on_char_hook(fake_f1)
                mock_open.assert_called_once_with(frame)

            with mock.patch("src.controllers.gui_update_dialog.wx.MessageBox") as mock_box:
                show_about_dialog(frame)
                mock_box.assert_called_once()
                self.assertIn("F1", mock_box.call_args.args[0])
        finally:
            frame.Destroy()
            wx.YieldIfNeeded()
            app.ExitMainLoop()
            del frame, app
            gc.collect()

    def test_scenario_05_cli_help_manual_flag(self) -> None:
        out_buf = io.StringIO()
        with (
            mock.patch("book_translator.open_user_manual", return_value=r"C:\tmp\manual_usuario.html") as mock_open,
            mock.patch.object(sys, "argv", ["book_translator.py", "--help-manual"]),
            redirect_stdout(out_buf),
        ):
            rc = book_translator.main()
        self.assertEqual(rc, 0)
        mock_open.assert_called_once_with()
        self.assertIn("Manual do usuário gerado e aberto no navegador:", out_buf.getvalue())
        self.assertIn("manual_usuario.html", out_buf.getvalue())

    def test_scenario_06_gui_resilient_error_handling_on_manual_failure(self) -> None:
        app = wx.App(False)
        frame = BookProcessorFrame(enable_startup_update_check=False)
        try:
            with (
                mock.patch("src.controllers.gui_update_dialog.open_user_manual", side_effect=OSError("disco cheio")),
                mock.patch("src.controllers.gui_update_dialog.wx.MessageBox") as mock_box,
            ):
                res = open_help_manual_from_gui(frame)
            self.assertIsNone(res)
            mock_box.assert_called_once()
            self.assertIn("disco cheio", mock_box.call_args.args[0])
        finally:
            frame.Destroy()
            wx.YieldIfNeeded()
            app.ExitMainLoop()
            del frame, app
            gc.collect()


if __name__ == "__main__":
    unittest.main()
