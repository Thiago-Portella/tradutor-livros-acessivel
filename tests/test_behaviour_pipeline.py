# Role: adapter
"""Testes de comportamento dos cenários 1 a 4 (Pipeline, fatiamento, SQLite WAL e pausa)."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import ssl
import tempfile
import unittest
import urllib.parse
import zipfile
from contextlib import ExitStack
from unittest import mock

import pymupdf

from book_translator import enhance_only_book_pipeline, translate_book_pipeline
from extractor import EnhancementOptions
from src.adapters import google_translate_client
from translator import TranslationCacheDB, translate_paragraphs_batch


def _create_sample_epub(path: str, title: str, chapters: list[tuple[str, list[str]]]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        manifest = []
        spine = []
        for idx, (ctitle, paras) in enumerate(chapters, start=1):
            fname = f"cap_{idx}.xhtml"
            manifest.append(f'<item id="c{idx}" href="{fname}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="c{idx}"/>')
            body = "".join(f"<p>{p}</p>" for p in paras)
            zf.writestr(f"OEBPS/{fname}", f"<html><body><h1>{ctitle}</h1>{body}</body></html>")
        opf = (
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/opf" version="3.0">'
            f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title><dc:creator>Autor Teste</dc:creator></metadata>'
            f'<manifest>{"".join(manifest)}</manifest><spine>{"".join(spine)}</spine></package>'
        )
        zf.writestr("OEBPS/content.opf", opf)


def _create_sample_pdf(path: str, pages_text: list[str]) -> None:
    doc = pymupdf.open()
    for txt in pages_text:
        pg = doc.new_page()
        pg.insert_text((72, 100), txt, fontsize=12)
    doc.save(path)
    doc.close()


class _FakeHttpResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class BehaviourPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_ssl = ssl._create_default_https_context

    def tearDown(self) -> None:
        self.assertIs(ssl._create_default_https_context, self._orig_ssl)

    def _make_fake_opener(self, recorded_queries: list[str], detected_lang: str = "es"):
        class _Opener:
            def open(self, req, timeout=15.0):
                parsed = urllib.parse.urlparse(req.full_url)
                qs = urllib.parse.parse_qs(parsed.query)
                q_text = qs["query.text"][0]
                recorded_queries.append(q_text)
                parts = q_text.split("\n\n")
                translated = "\n\n".join(f"[PT] {p}" for p in parts)
                payload = [translated, [[translated]], None, None, None, detected_lang]
                return _FakeHttpResp(json.dumps(payload).encode("utf-8"))

        return _Opener()

    def test_scenario_01_concrete_usage_example(self) -> None:
        queries: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            epub_in = os.path.join(tmp, "livro_espanhol.epub")
            html_out = os.path.join(tmp, "saida", "livro_pt.html")
            pdf_in = os.path.join(tmp, "obra_em_ingles.pdf")
            epub_out = os.path.join(tmp, "saida", "obra_limpa.epub")

            _create_sample_epub(
                epub_in,
                "El Libro Original",
                [("Capítulo Uno", ["Primera frase larga en español."]), ("Capítulo Dos", ["Segunda frase."])],
            )
            _create_sample_pdf(pdf_in, ["Chapter 1\n\nFirst clean paragraph in English."])

            cache_target = os.path.join(tmp, "cache_s1.sqlite3")
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(google_translate_client, "_create_opener", return_value=self._make_fake_opener(queries, "es")))
                stack.enter_context(mock.patch("src.services.book_pipeline.get_default_cache_path", return_value=cache_target))

                opts = EnhancementOptions(
                    normalize_chars=True,
                    reflow_sentences=True,
                    remove_headers_footers=True,
                    organize_toc=True,
                    footnote_mode="move_end",
                    include_back_to_toc=False,
                )
                book = translate_book_pipeline(
                    input_path=epub_in,
                    output_path=html_out,
                    output_format="html",
                    source_lang="auto",
                    target_lang="pt",
                    bilingual=True,
                    options=opts,
                    start_page=1,
                    end_page=5,
                )
                self.assertNotEqual(book.original_title, "")
                self.assertEqual(book.original_title, "El Libro Original")
                self.assertEqual(book.detected_source_lang, "es")
                with open(html_out, encoding="utf-8") as fh_html:
                    html_text = fh_html.read()
                self.assertIn('lang="es"', html_text)
                self.assertIn("El Libro Original", html_text)

                enhanced = enhance_only_book_pipeline(
                    input_path=pdf_in,
                    output_path=epub_out,
                    output_format="epub",
                    doc_lang="en",
                    options=opts,
                )
                self.assertEqual(len(enhanced.chapters), 1)
                with zipfile.ZipFile(epub_out, "r") as zf:
                    opf = zf.read("OEBPS/content.opf").decode("utf-8")
                    self.assertIn("<dc:language>en</dc:language>", opf)

    def test_scenario_02_long_and_non_ascii_paragraphs_split_safely(self) -> None:
        queries: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            cache_db = TranslationCacheDB(os.path.join(tmp, "c.sqlite3"))
            long_latin = " ".join(f"Sentence number {i} is complete and valid." for i in range(130))
            long_cyrillic = " ".join(f"Предложение номер {i} очень длинное и важное." for i in range(60))
            self.assertGreater(len(long_latin), 4500)
            self.assertGreater(len(urllib.parse.quote(long_cyrillic, safe="")), 12000)

            with mock.patch.object(google_translate_client, "_create_opener", return_value=self._make_fake_opener(queries, "ru")):
                res = translate_paragraphs_batch(
                    [long_latin, long_cyrillic],
                    target_lang="pt",
                    source_lang="auto",
                    cache_db=cache_db,
                    min_request_interval=0.0,
                )

            self.assertEqual(len(res), 2)
            self.assertGreater(len(queries), 2)
            for q in queries:
                self.assertLessEqual(len(q), 3600)
                self.assertLessEqual(len(urllib.parse.quote(q, safe="")), 10500)
            self.assertIsNotNone(cache_db.get(long_latin, "auto", "pt"))
            self.assertIsNotNone(cache_db.get(long_cyrillic, "auto", "pt"))

    def test_scenario_03_sqlite_wal_and_global_ssl_unmodified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "wal_test.sqlite3")
            cache_db = TranslationCacheDB(db_path)
            cache_db.put("Hello", "Olá", "en", "pt")
            conn = sqlite3.connect(db_path)
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            conn.close()
            self.assertEqual(mode.lower(), "wal")
            self.assertIs(ssl._create_default_https_context, self._orig_ssl)

    def test_scenario_04_partial_export_only_on_pause(self) -> None:
        queries: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            md_in = os.path.join(tmp, "livro.md")
            epub_out = os.path.join(tmp, "livro_final.epub")
            partial_out = os.path.join(tmp, "livro_final_parcial.epub")
            cache_target = os.path.join(tmp, "cache_s4.sqlite3")

            ch1_paras = "\n\n".join(
                f"Parágrafo 1.{j}: " + ("conteudo longo para ultrapassar o orcamento de lote unico em varios envios. " * 3)
                for j in range(25)
            )
            ch2_paras = "\n\n".join(f"Parágrafo 2.{j}: segundo capítulo." for j in range(10))
            with open(md_in, "w", encoding="utf-8") as f:
                f.write(f"# Capítulo 1\n\n{ch1_paras}\n\n# Capítulo 2\n\n{ch2_paras}")

            first_batch_done = False

            def _cancel_after_first_group() -> bool:
                return first_batch_done

            def _cb(done: int, total: int, _status_text: str, _prev: str) -> None:
                nonlocal first_batch_done
                if done >= 10:
                    first_batch_done = True

            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(google_translate_client, "_create_opener", return_value=self._make_fake_opener(queries, "en")))
                stack.enter_context(mock.patch("src.services.book_pipeline.get_default_cache_path", return_value=cache_target))

                translate_book_pipeline(
                    input_path=md_in,
                    output_path=epub_out,
                    output_format="epub",
                    source_lang="en",
                    target_lang="pt",
                    cancel_check=_cancel_after_first_group,
                    status_callback=_cb,
                )

            self.assertFalse(os.path.exists(epub_out))
            self.assertTrue(os.path.exists(partial_out))
            with zipfile.ZipFile(partial_out, "r") as zf:
                ch_files = [n for n in zf.namelist() if n.startswith("OEBPS/chapter_")]
                self.assertEqual(len(ch_files), 1)
                ch1_html = zf.read(ch_files[0]).decode("utf-8")
                self.assertIn("Parágrafo 1.0", ch1_html)
                self.assertNotIn("Parágrafo 1.24", ch1_html)


if __name__ == "__main__":
    unittest.main()
