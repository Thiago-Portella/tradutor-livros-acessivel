# Role: service
"""Fachada pública compatível do motor de tradução e cache SQLite WAL."""

from __future__ import annotations

from src.adapters.google_translate_client import (
    GOOGLE_TRANSLATE_API_KEY,
    GOOGLE_TRANSLATE_CLIENT,
    GOOGLE_TRANSLATE_URL,
    google_translate,
)
from src.adapters.sqlite_cache import TranslationCacheDB
from src.domain.models import TranslationError, TranslationRateLimitError
from src.policies.i18n_labels import LANGUAGES
from src.policies.text_normalizer import clean_text_for_translate
from src.services.batch_translator import translate_paragraphs_batch

__all__ = [
    "LANGUAGES",
    "GOOGLE_TRANSLATE_URL",
    "GOOGLE_TRANSLATE_CLIENT",
    "GOOGLE_TRANSLATE_API_KEY",
    "TranslationError",
    "TranslationRateLimitError",
    "TranslationCacheDB",
    "clean_text_for_translate",
    "google_translate",
    "translate_paragraphs_batch",
]
