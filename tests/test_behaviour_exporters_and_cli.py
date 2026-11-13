# Role: adapter
"""Testes de comportamento dos cenários 8 a 12 (Exportação, PDF, GUI e EXE CLI)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pymupdf
import wx

from epub_builder import export_book
from extractor import BookStructure, Chapter, ParagraphItem
from src.controllers.gui_frame import BookProcessorFrame
from translator import TranslationError

ROOT_DIR = Path(__file__).resolve().parent.parent


def _collect_mnemonics(root: wx.Window) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if hasattr(root, "GetMenuBar") and root.GetMenuBar() is not None:
        menu_bar = root.GetMenuBar()
        for idx in range(menu_bar.GetMenuCount()):
            lbl = menu_bar.GetMenuLabel(idx)
            if "&" in lbl:
                pos = lbl.find("&")
                if pos + 1 < len(lbl) and lbl[pos + 1] not in (" ", "&"):
                    found.append((lbl[pos + 1].upper(), f"Menu:{lbl}"))
    for child in root.GetChildren():
        lbl = child.GetLabel() if hasattr(child, "GetLabel") else ""
        if "&" in lbl:
            idx = lbl.find("&")
            if idx + 1 < len(lbl) and lbl[idx + 1] not in (" ", "&"):
                found.append((lbl[idx + 1].upper(), lbl))
        found.extend(_collect_mnemonics(child))
    return found


class BehaviourExportersAndCliTests(unittest.TestCase):
    def test_scenario_08_localized_labels_and_bilingual_lang(self) -> None:
        book = BookStructure(
            title="The Great Book",
            original_title="El Gran Libro",
            author="Jane Doe",
            source_path="in.epub",
            detected_source_lang="es",
            chapters=[
                Chapter(
                    index=1,
                    title="Capítulo Uno",
                    translated_title="Chapter One",
                    start_page=1,
                    end_page=1,
                    items=[ParagraphItem(text="Hola mundo.", translated_text="Hello world.")],
                )
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            for ext in ("html", "epub", "md", "txt"):
                out_p = os.path.join(tmp, f"out.{ext}")
                export_book(book, out_p, fmt=ext, target_lang="en", source_lang="auto", bilingual=True, include_back_to_toc=True)
                self.assertTrue(os.path.exists(out_p))
            with open(os.path.join(tmp, "out.html"), encoding="utf-8") as hf:
                html_s = hf.read()
            self.assertIn("Table of Contents", html_s)
            self.assertIn("Author:", html_s)
            self.assertIn('lang="es"', html_s)
            self.assertIn("El Gran Libro", html_s)
            with open(os.path.join(tmp, "out.txt"), encoding="utf-8") as tf:
                txt_s = tf.read()
            self.assertIn("TABLE OF CONTENTS", txt_s)
            self.assertIn("CHAPTER 1:", txt_s)

    def test_scenario_09_pdf_long_url_unicode_and_escaped_names(self) -> None:
        long_url = "https://exemplo.com/" + ("a" * 170)
        book = BookStructure(
            title="Livro (Edição Especial)",
            original_title="Book (Special)",
            author="Autor",
            source_path="in.txt",
            chapters=[
                Chapter(
                    index=1,
                    title="Capítulo Único (Teste)",
                    start_page=1,
                    end_page=1,
                    items=[
                        ParagraphItem(text=long_url),
                        ParagraphItem(text="Привет мир! 你好世界!"),
                    ],
                )
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            pdf_out = os.path.join(tmp, "unicode_url.pdf")
            export_book(book, pdf_out, fmt="pdf", target_lang="pt")
            with pymupdf.open(pdf_out) as doc:
                self.assertGreaterEqual(len(doc), 3)
                full_txt = "\n".join(pg.get_text("text") for pg in doc)
                self.assertIn("Привет мир", full_txt)
                self.assertIn("你好世界", full_txt)
                toc_titles = [row[1] for row in doc.get_toc()]
                self.assertTrue(any("Capítulo Único (Teste)" in t for t in toc_titles))
                raw_objs = "\n".join(doc.xref_object(x) for x in range(1, doc.xref_length()))
                self.assertIn(r"\(Teste\)", raw_objs)
                # Verifica que nenhuma palavra ultrapassa a margem direita (x1 <= 595 - 60)
                for pg in doc[2:]:
                    for blk in pg.get_text("blocks"):
                        self.assertLessEqual(blk[2], 545.0)

    def test_scenario_10_locked_output_file_error_without_temp_residue(self) -> None:
        book = BookStructure(
            title="Teste",
            author="Autor",
            source_path="in.txt",
            chapters=[Chapter(index=1, title="Cap 1", start_page=1, end_page=1, items=[ParagraphItem(text="Olá.")])],
        )
        with tempfile.TemporaryDirectory() as tmp:
            out_p = os.path.join(tmp, "travado.pdf")
            with mock.patch("src.adapters.atomic_file_writer.os.replace", side_effect=PermissionError("locked")):
                with self.assertRaises(TranslationError) as ctx:
                    export_book(book, out_p, fmt="pdf")
            self.assertIn("aberto em outro programa", str(ctx.exception))
            leftovers = [f for f in os.listdir(tmp) if f.startswith(".tmp_")]
            self.assertEqual(leftovers, [])

    def test_scenario_11_gui_mnemonics_doc_lang_and_async_preview(self) -> None:
        import threading

        app = wx.App(False)
        frame = BookProcessorFrame()
        try:
            top_mnems = _collect_mnemonics(frame)
            for tab in (frame.tab_translate, frame.tab_enhance):
                mnems = [m for m in top_mnems if m[1].startswith("Menu:")] + _collect_mnemonics(tab)
                self.assertGreaterEqual(len(mnems), 21)
                seen: dict[str, str] = {}
                for key, lbl in mnems:
                    self.assertNotIn(key, seen, f"Colisão de Alt+{key}: '{seen.get(key)}' vs '{lbl}'")
                    seen[key] = lbl
            self.assertIsNotNone(frame.tab_enhance.cmb_doc_lang)
            self.assertIsNone(frame.tab_translate.cmb_doc_lang)

            with tempfile.TemporaryDirectory() as tmp:
                md_in = os.path.join(tmp, "previa.md")
                with open(md_in, "w", encoding="utf-8") as f:
                    f.write("# Seção Um\n\nTexto curto.\n\n# Seção Dois\n\nOutro texto.")
                frame.tab_translate.txt_input.SetValue(md_in)
                frame.tab_translate._on_preview_toc(None)
                self.assertIsNotNone(frame.tab_translate._preview_thread)
                frame.tab_translate._preview_thread.join(timeout=5.0)
                wx.YieldIfNeeded()
                self.assertIn("Seção Um", frame.tab_translate.txt_log.GetValue())
                self.assertTrue(frame.tab_translate.btn_preview_toc.IsEnabled())

            stop_gate = threading.Event()

            def _busy_worker() -> None:
                while not frame.tab_translate._cancel_requested and not stop_gate.is_set():
                    stop_gate.wait(0.02)

            frame.tab_translate._is_running = True
            frame.tab_translate._cancel_requested = False
            frame.tab_translate._worker_thread = threading.Thread(target=_busy_worker, daemon=True)
            frame.tab_translate._worker_thread.start()

            fake_esc = mock.MagicMock()
            fake_esc.GetKeyCode.return_value = wx.WXK_ESCAPE
            with mock.patch("src.controllers.gui_frame.wx.GetActiveWindow", return_value=frame):
                with mock.patch.object(frame, "Close") as mock_close:
                    frame._on_char_hook(fake_esc)
                    mock_close.assert_not_called()

                    frame.tab_translate.cancel_and_wait(timeout_sec=2.0)
                    stop_gate.set()
                    self.assertTrue(frame.tab_translate._cancel_requested)
                    self.assertFalse(frame.tab_translate._worker_thread.is_alive())
                    frame.tab_translate._is_running = False

                    frame._on_char_hook(fake_esc)
                    mock_close.assert_called_once()
        finally:
            frame.Destroy()
            wx.YieldIfNeeded()
            app.ExitMainLoop()

    def test_scenario_12_compiled_exe_cli_mode(self) -> None:
        exe_path = ROOT_DIR / "dist" / "TradutorLivros" / "TradutorLivros.exe"
        self.assertTrue(exe_path.exists(), f"Executável ausente: {exe_path}")
        help_proc = subprocess.run(
            [str(exe_path), "--help"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20
        )
        self.assertEqual(help_proc.returncode, 0)

        with tempfile.TemporaryDirectory() as tmp:
            md_in = os.path.join(tmp, "cli_teste.md")
            epub_out = os.path.join(tmp, "cli_saida.epub")
            with open(md_in, "w", encoding="utf-8") as f:
                f.write("# Capítulo Teste\n\nParágrafo de verificação real pelo executável.")
            proc = subprocess.run(
                [str(exe_path), md_in, "--cli", "--enhance-only", "--doc-lang", "pt", "-f", "epub", "-o", epub_out],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")
            self.assertTrue(os.path.exists(epub_out))


if __name__ == "__main__":
    unittest.main()
