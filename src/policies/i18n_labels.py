# Role: policy
"""Catálogo de idiomas suportados e localização de rótulos estruturais dos livros."""

from __future__ import annotations

from dataclasses import dataclass

LANGUAGES = {
    "auto": "Detectar idioma automaticamente",
    "af": "Africâner", "ar": "Árabe", "bg": "Búlgaro", "bn": "Bengali",
    "ca": "Catalão", "cs": "Tcheco", "cy": "Galês", "da": "Dinamarquês",
    "de": "Alemão", "el": "Grego", "en": "Inglês", "eo": "Esperanto",
    "es": "Espanhol", "et": "Estoniano", "eu": "Basco", "fa": "Persa",
    "fi": "Finlandês", "fr": "Francês", "ga": "Irlandês", "gl": "Galego",
    "he": "Hebraico", "hi": "Hindi", "hr": "Croata", "hu": "Húngaro",
    "id": "Indonésio", "is": "Islandês", "it": "Italiano", "ja": "Japonês",
    "ko": "Coreano", "la": "Latim", "lt": "Lituano", "lv": "Letão",
    "ms": "Malaio", "nl": "Holandês", "no": "Norueguês", "pl": "Polonês",
    "pt": "Português", "ro": "Romeno", "ru": "Russo", "sk": "Eslovaco",
    "sl": "Esloveno", "sr": "Sérvio", "sv": "Sueco", "sw": "Suaíli",
    "th": "Tailandês", "tr": "Turco", "uk": "Ucraniano", "ur": "Urdu",
    "vi": "Vietnamita", "zh": "Chinês (Simplificado)", "zh-TW": "Chinês (Tradicional)",
}


@dataclass(frozen=True)
class BookLabels:
    toc_title: str
    author_label: str
    chapter_word: str
    back_to_toc: str
    end_of_chapter_note: str
    page_abbr: str
    chapter_notes: str


_LOCALIZED_BOOK_LABELS = {
    "pt": BookLabels("Sumário", "Autor", "Capítulo", "↑ Voltar ao Sumário",
                     "[Fim do Capítulo - Consulte o Sumário no início do documento]", "Pág.", "Notas do Capítulo"),
    "en": BookLabels("Table of Contents", "Author", "Chapter", "↑ Back to Table of Contents",
                     "[End of Chapter - See Table of Contents at the beginning]", "Page", "Chapter Notes"),
    "es": BookLabels("Índice", "Autor", "Capítulo", "↑ Voltar al Índice",
                     "[Fin del Capítulo - Consulte el Índice al inicio del documento]", "Pág.", "Notas del Capítulo"),
    "fr": BookLabels("Table des matières", "Auteur", "Chapitre", "↑ Retour à la table des matières",
                     "[Fin du chapitre - Consultez la table des matières au début]", "Page", "Notes du chapitre"),
    "de": BookLabels("Inhaltsverzeichnis", "Autor", "Kapitel", "↑ Zurück zum Inhaltsverzeichnis",
                     "[Kapitelende - Siehe Inhaltsverzeichnis am Anfang]", "Seite", "Kapitelanmerkungen"),
    "it": BookLabels("Indice", "Autore", "Capitolo", "↑ Torna all'Indice",
                     "[Fine del capitolo - Consulta l'Indice all'inizio]", "Pag.", "Note del capitolo"),
    "ru": BookLabels("Содержание", "Автор", "Глава", "↑ Назад к содержанию",
                     "[Конец главы - см. Содержание в начале документа]", "Стр.", "Примечания к главе"),
    "zh": BookLabels("目录", "作者", "第", "↑ 返回目录", "[本章结束 - 请参阅文档开头的目录]", "页", "本章注释"),
    "ja": BookLabels("目次", "著者", "第", "↑ 目次へ戻る", "[章の終わり - 文書先頭の目次を参照してください]", "ページ", "章の注記"),
    "ko": BookLabels("목차", "저자", "장", "↑ 목차로 돌아가기", "[장 끝 - 문서 시작 부분의 목차를 참조하세요]", "쪽", "장 주석"),
    "ar": BookLabels("الفهرس", "المؤلف", "الفصل", "↑ العودة إلى الفهرس", "[نهاية الفصل - راجع الفهرس في البداية]", "صفحة", "ملاحظات الفصل"),
}


def get_ui_book_labels(lang_code: str) -> BookLabels:
    code = (lang_code or "pt").strip().lower()
    if code in _LOCALIZED_BOOK_LABELS:
        return _LOCALIZED_BOOK_LABELS[code]
    prefix = code.split("-", 1)[0]
    if prefix in _LOCALIZED_BOOK_LABELS:
        return _LOCALIZED_BOOK_LABELS[prefix]
    return _LOCALIZED_BOOK_LABELS["en"]


def describe_toc_method(method: str) -> str:
    descriptions = {
        "embedded_toc": "Sumário original embutido no PDF",
        "heuristic_typography": "Algoritmo tipográfico (capítulos descobertos pelo layout/fontes)",
        "printed_toc_parser": "Algoritmo leitor de página de Sumário impressa",
        "smart_page_chunks": "Divisão automática inteligente por blocos de páginas",
        "epub_spine": "Estrutura de capítulos do EPUB",
        "heuristic_txt": "Detecção automática de títulos de capítulos no texto",
        "auto_segmented_txt": "Segmentação automática em capítulos para texto contínuo",
        "single_section": "Seção única contínua",
    }
    return descriptions.get(method, method)
