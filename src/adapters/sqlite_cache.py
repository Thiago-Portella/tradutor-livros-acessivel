# Role: adapter
"""Persistência local de traduções em SQLite com modo WAL e controle concorrente."""

from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3
import threading
import time
from typing import List, Optional, Tuple

from src.policies.text_normalizer import clean_text_for_translate


class TranslationCacheDB:
    """Banco de dados SQLite local em modo WAL para retomar traduções sem perda."""

    def __init__(self, db_path: str):
        abs_path = os.path.abspath(db_path)
        if len(abs_path) > 220:
            abs_path = self._make_fallback_path(abs_path)
        self.db_path = abs_path
        self._lock = threading.Lock()
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._init_db()
        except (OSError, sqlite3.OperationalError):
            self.db_path = self._make_fallback_path(abs_path)
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._init_db()

    @staticmethod
    def _make_fallback_path(original_path: str) -> str:
        fallback_dir = os.path.join(os.path.expanduser("~"), ".tradutor_livros_cache")
        h = hashlib.sha256(original_path.lower().encode("utf-8")).hexdigest()[:16]
        return os.path.join(fallback_dir, f"cache_{h}.sqlite3")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS translations (
                    cache_key TEXT PRIMARY KEY,
                    source_lang TEXT,
                    target_lang TEXT,
                    original_text TEXT,
                    translated_text TEXT,
                    updated_at REAL
                )
                """
            )
            conn.commit()

    @staticmethod
    def make_key(text: str, source_lang: str, target_lang: str) -> str:
        norm = clean_text_for_translate(text)
        raw = f"{source_lang}|{target_lang}|{norm}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def get(self, text: str, source_lang: str, target_lang: str) -> Optional[str]:
        if not text or not text.strip():
            return text
        key = self.make_key(text, source_lang, target_lang)
        with self._lock, contextlib.closing(self._connect()) as conn:
            cur = conn.execute(
                "SELECT translated_text FROM translations WHERE cache_key = ?",
                (key,),
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                return None
            val = row[0]
            for zw in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"):
                val = val.replace(zw, "")
            return val

    def put(self, text: str, translated: str, source_lang: str, target_lang: str) -> None:
        if not text or not text.strip() or not translated:
            return
        key = self.make_key(text, source_lang, target_lang)
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO translations
                (cache_key, source_lang, target_lang, original_text, translated_text, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key, source_lang, target_lang, text, translated, time.time()),
            )
            conn.commit()

    def put_many(
        self,
        pairs: List[Tuple[str, str]],
        source_lang: str,
        target_lang: str,
    ) -> None:
        now = time.time()
        rows = []
        for orig, trans in pairs:
            if orig and orig.strip() and trans:
                key = self.make_key(orig, source_lang, target_lang)
                rows.append((key, source_lang, target_lang, orig, trans, now))
        if not rows:
            return
        with self._lock, contextlib.closing(self._connect()) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO translations
                (cache_key, source_lang, target_lang, original_text, translated_text, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
