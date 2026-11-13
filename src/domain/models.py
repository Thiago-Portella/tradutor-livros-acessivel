# Role: value
"""Estruturas imutáveis e modelos de dados do domínio do livro."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

SUPPORTED_FORMATS = {
    "epub": ("Livro Digital EPUB 3 (.epub)", ".epub"),
    "pdf": ("Documento PDF com Marcadores (.pdf)", ".pdf"),
    "html": ("Página Web Acessível HTML5 (.html)", ".html"),
    "md": ("Documento Markdown Estruturado (.md)", ".md"),
    "txt": ("Texto Puro com Sumário (.txt)", ".txt"),
}

FOOTNOTE_MODES = {
    "move_end": "Mover notas de rodapé para o fim do capítulo (Recomendado)",
    "remove": "Remover notas de rodapé completamente",
    "keep": "Manter notas de rodapé onde estão",
}


class TranslationError(Exception):
    """Exceção base para falhas de tradução ou exportação."""


class TranslationRateLimitError(TranslationError):
    """Exceção lançada quando a API retorna limite de requisições (HTTP 429)."""


@dataclass
class EnhancementOptions:
    """Opções granulares de aprimoramento estrutural e textual do livro."""

    normalize_chars: bool = True
    reflow_sentences: bool = True
    remove_headers_footers: bool = True
    organize_toc: bool = True
    force_heuristic_toc: bool = False
    footnote_mode: str = "move_end"
    include_back_to_toc: bool = False


@dataclass
class ParagraphItem:
    text: str
    kind: str = "p"
    page_number: int = 1
    translated_text: Optional[str] = None


@dataclass
class Chapter:
    index: int
    title: str
    start_page: int
    end_page: int
    translated_title: Optional[str] = None
    items: List[ParagraphItem] = field(default_factory=list)


@dataclass
class BookStructure:
    title: str
    author: str
    source_path: str
    chapters: List[Chapter] = field(default_factory=list)
    toc_discovery_method: str = "embedded"
    original_title: str = ""
    detected_source_lang: str = ""
