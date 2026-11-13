# Role: adapter
"""Testes de comportamento dos cenários 5 a 7 (EPUB parser, Markdown/bounds e PDF)."""

from __future__ import annotations

import os
import tempfile
import unittest
import zipfile

import pymupdf

from extractor import EnhancementOptions, extract_book, extract_epub_book, extract_pdf_book


class BehaviourExtractorsTests(unittest.TestCase):
    def test_scenario_05_epub_structural_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            epub_path = os.path.join(tmp, "estrutural.epub")
            xhtml = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Ignored</title>'
                '<style>.x{color:red}</style><script>var secret = 1;</script></head>'
                '<body><h1>Título&nbsp;&mdash;&nbsp;Teste&#8217;s</h1>'
                '<div><p>Primeiro parágrafo <b>aninhado</b> &mdash; ok.</p></div>'
                '<div>Bloco Um</div><div>Bloco Dois</div></body></html>'
            )
            opf = (
                '<?xml version="1.0"?><package xmlns="http://www.idpf.org/opf" version="3.0">'
                '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Estrutural</dc:title></metadata>'
                '<manifest><item id="c1" href="Text/Cap%201.xhtml" media-type="application/xhtml+xml"/></manifest>'
                '<spine><itemref idref="c1"/></spine></package>'
            )
            with zipfile.ZipFile(epub_path, "w") as zf:
                zf.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
                zf.writestr("OEBPS/content.opf", opf)
                zf.writestr("OEBPS/Text/Cap 1.xhtml", xhtml)

            book = extract_epub_book(epub_path)
            self.assertEqual(len(book.chapters), 1)
            ch = book.chapters[0]
            self.assertIn("—", ch.title)
            self.assertIn("Teste’s", ch.title)
            texts = [it.text for it in ch.items]
            joined = "\n".join(texts)
            self.assertIn("Primeiro parágrafo aninhado — ok.", texts)
            self.assertIn("Bloco Um", texts)
            self.assertIn("Bloco Dois", texts)
            self.assertNotIn("Bloco UmBloco Dois", joined)
            self.assertNotIn("secret", joined)
            self.assertNotIn("color:red", joined)

    def test_scenario_06_markdown_hash_and_universal_page_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            md_path = os.path.join(tmp, "curso.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(
                    "# C# Avançado\n\nIntrodução ao C#.\n\n"
                    "# F# Funcional\n\nIntrodução ao F#.\n\n"
                    "# Python Moderno\n\n- Item A\n- Item B\n\n"
                    "# Rust Seguro\n\nFim."
                )

            sliced = extract_book(md_path, start_page=1, end_page=2)
            self.assertEqual(len(sliced.chapters), 2)
            self.assertEqual(sliced.chapters[0].title, "C# Avançado")
            self.assertEqual(sliced.chapters[1].title, "F# Funcional")

            with self.assertRaises(ValueError):
                extract_book(md_path, start_page=4, end_page=2)
            with self.assertRaises(ValueError):
                extract_book(md_path, start_page=0, end_page=2)

    def test_scenario_07_pdf_page2_same_page_toc_and_reflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # 1. PDF de 45 páginas com capítulo legítimo na página 2 + frase partida entre páginas
            pdf_long = os.path.join(tmp, "longo_45p.pdf")
            doc = pymupdf.open()
            p1 = doc.new_page()
            p1.insert_text((72, 120), "LIVRO DE TESTE LONGO", fontsize=22)

            p2 = doc.new_page()
            p2.insert_text((72, 100), "Abertura Especial", fontsize=18)
            p2.insert_text((72, 140), "Este texto começa na página dois e continua sem ponto final para a página seguinte", fontsize=11)

            p3 = doc.new_page()
            p3.insert_text((72, 100), "até terminar com clareza aqui.", fontsize=11)
            for pg_i in range(4, 46):
                pg = doc.new_page()
                if pg_i in (12, 25):
                    pg.insert_text((72, 100), f"SEÇÃO IMPORTANTE {pg_i}", fontsize=18)
                pg.insert_text((72, 140), f"Conteúdo regular da página {pg_i}.", fontsize=11)
            doc.save(pdf_long)
            doc.close()

            book_long = extract_pdf_book(pdf_long, EnhancementOptions(force_heuristic_toc=True))
            titles_long = [c.title for c in book_long.chapters]
            self.assertTrue(any("Abertura Especial" in t for t in titles_long), f"Títulos: {titles_long}")

            # 2. PDF com TOC embutido contendo 2 capítulos na mesma página (pág. 2) + reflow entre págs
            pdf_same = os.path.join(tmp, "same_page_toc.pdf")
            doc2 = pymupdf.open()
            pg1 = doc2.new_page()
            pg1.insert_text((72, 100), "Capa", fontsize=20)
            pg2 = doc2.new_page()
            pg2.insert_text((72, 90), "Primeiro Na Mesma Página", fontsize=16)
            pg2.insert_text((72, 120), "Texto do primeiro capítulo.", fontsize=11)
            pg2.insert_text((72, 220), "Segundo Na Mesma Página", fontsize=16)
            pg2.insert_text((72, 250), "Frase quebrada na virada de", fontsize=11)
            pg3 = doc2.new_page()
            pg3.insert_text((72, 100), "página para testar o reflow.", fontsize=11)
            doc2.set_toc([[1, "Primeiro Na Mesma Página", 2], [1, "Segundo Na Mesma Página", 2]])
            doc2.save(pdf_same)
            doc2.close()

            book_same = extract_pdf_book(pdf_same)
            self.assertEqual(len(book_same.chapters), 2)
            self.assertEqual(book_same.chapters[0].title, "Primeiro Na Mesma Página")
            self.assertEqual(book_same.chapters[1].title, "Segundo Na Mesma Página")
            joined_ch2 = " ".join(it.text for it in book_same.chapters[1].items)
            self.assertIn("Frase quebrada na virada de página para testar o reflow.", joined_ch2)


if __name__ == "__main__":
    unittest.main()
