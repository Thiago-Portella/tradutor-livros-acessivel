"""
Módulo de tradução baseado no motor Google Translate do addon Absolute Translate para NVDA.
Utiliza o endpoint moderno translate-pa.googleapis.com com suporte a lotes de parágrafos,
retentativas com backoff exponencial e cache persistente em SQLite.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import re
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request as urllibRequest
from typing import Callable, List, Optional, Tuple

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

# Endpoint oficial de produção usado pelo frontend web do Google Tradutor e pelo Absolute Translate
GOOGLE_TRANSLATE_URL = "https://translate-pa.googleapis.com/v1/translate"
GOOGLE_TRANSLATE_CLIENT = "gtx"
_GOOGLE_TRANSLATE_KEY_PARTS = ("AIzaSyDLEeFI5OtFBwYBIoK_jj5", "m32rZK5CkCXA")
GOOGLE_TRANSLATE_API_KEY = "".join(_GOOGLE_TRANSLATE_KEY_PARTS)

MAX_CHARS_GOOGLE = 4200

# Ignora erros de certificado SSL em sistemas com cadeias desatualizadas (mesmo padrão do Absolute Translate)
ssl._create_default_https_context = ssl._create_unverified_context


class TranslationError(Exception):
    """Exceção base para falhas de tradução."""


class TranslationRateLimitError(TranslationError):
    """Exceção lançada quando a API retorna HTTP 429 (Too Many Requests)."""


def _create_opener() -> urllibRequest.OpenerDirector:
    opener = urllibRequest.build_opener()
    opener.addheaders = [
        (
            "User-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ),
        ("Referer", "https://translate.google.com/"),
        ("Accept-Language", "en-US,en;q=0.9"),
    ]
    return opener


def clean_text_for_translate(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    return cleaned.strip()


def _parse_google_response(data: object) -> Tuple[str, Optional[str]]:
    """Analisa a resposta JSON do translate-pa.googleapis.com."""
    if not isinstance(data, list) or not data:
        return "", None
    sentences = data[1] if len(data) > 1 else None
    if sentences and isinstance(sentences, list):
        translation = "".join(s[0] for s in sentences if s and s[0])
    else:
        translation = data[0] or ""
    for zw in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"):
        translation = translation.replace(zw, "")
    detected = data[5] if len(data) > 5 and data[5] else None
    return translation, detected


def google_translate(
    text: str,
    target_lang: str = "pt",
    source_lang: str = "auto",
    retry: int = 4,
) -> Tuple[str, str]:
    """
    Traduz um texto usando o endpoint translate-pa.googleapis.com do Absolute Translate.
    Retorna a tupla (texto_traduzido, idioma_origem_detectado).
    """
    if not text or not text.strip():
        return text, source_lang

    cleaned_text = clean_text_for_translate(text)
    if not cleaned_text:
        return text, source_lang

    params = [
        ("params.client", GOOGLE_TRANSLATE_CLIENT),
        ("query.source_language", source_lang),
        ("query.target_language", target_lang),
        ("query.display_language", "en"),
        ("query.text", cleaned_text),
        ("key", GOOGLE_TRANSLATE_API_KEY),
        ("data_types", "TRANSLATION"),
        ("data_types", "SENTENCE_SPLITS"),
    ]
    url = f"{GOOGLE_TRANSLATE_URL}?{urllib.parse.urlencode(params)}"
    headers = {"Content-Type": "application/json+protobuf"}
    opener = _create_opener()

    base_delay = 0.6
    max_delay = 6.0
    max_total_wait_seconds = 45.0
    start_time = time.monotonic()

    for attempt in range(retry + 1):
        remaining = max_total_wait_seconds - (time.monotonic() - start_time)
        if remaining <= 0:
            raise TranslationError(
                f"Tempo limite de tradução excedido após {max_total_wait_seconds:.0f} segundos"
            )

        attempt_timeout = min(15.0, remaining)
        delay = min(
            min(base_delay * (2**attempt), max_delay) + random.uniform(0.05, 0.35),
            remaining,
        )

        try:
            req = urllibRequest.Request(url, headers=headers)
            with opener.open(req, timeout=attempt_timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            result, detected = _parse_google_response(data)
            if result:
                return result, (detected or source_lang)
            if attempt < retry:
                time.sleep(delay)
                continue
            raise TranslationError("Resposta inesperada da API de tradução")

        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if retry_after:
                    try:
                        delay = min(max(delay, float(retry_after)), remaining)
                    except ValueError:
                        pass
                if attempt < retry:
                    time.sleep(delay)
                    continue
                raise TranslationRateLimitError("HTTP 429: Muitas requisições na API de tradução") from e
            if attempt < retry:
                time.sleep(delay)
                continue
            raise TranslationError(f"Erro HTTP {e.code}: {e.reason}") from e

        except urllib.error.URLError as e:
            if attempt < retry:
                time.sleep(delay)
                continue
            raise TranslationError(f"Erro de conexão de rede: {e}") from e

        except TranslationError:
            raise

        except Exception as e:
            if attempt < retry:
                time.sleep(delay)
                continue
            raise TranslationError(f"Erro inesperado na tradução: {e}") from e

    raise TranslationError("Falha na tradução após todas as tentativas")


class TranslationCacheDB:
    """
    Banco de dados SQLite local para salvar cada parágrafo traduzido instantaneamente.
    Permite pausar, fechar o programa ou perder a conexão e retomar exatamente do ponto onde parou.
    """

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

    def _init_db(self) -> None:
        with self._lock, contextlib.closing(sqlite3.connect(self.db_path)) as conn:
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
        with self._lock, contextlib.closing(sqlite3.connect(self.db_path)) as conn:
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
        with self._lock, contextlib.closing(sqlite3.connect(self.db_path)) as conn:
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
        with self._lock, contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO translations
                (cache_key, source_lang, target_lang, original_text, translated_text, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()


def translate_paragraphs_batch(
    paragraphs: List[str],
    target_lang: str,
    source_lang: str,
    cache_db: TranslationCacheDB,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    min_request_interval: float = 0.25,
) -> List[str]:
    """
    Traduz uma lista de parágrafos agrupando os que ainda não estão no cache em lotes de até
    MAX_CHARS_GOOGLE caracteres separados por '\\n\\n'.
    Caso o Google altere o número de quebras de linha em algum lote específico, faz fallback
    automático para tradução individual daquele lote, garantindo alinhamento 1:1 perfeito
    (essencial para o modo bilíngue e para o cache por parágrafo).
    """
    total = len(paragraphs)
    results: List[Optional[str]] = [None] * total
    missing_indices: List[int] = []

    # 1. Verifica o que já está salvo no cache SQLite
    for i, p in enumerate(paragraphs):
        if not p or not p.strip():
            results[i] = p
            continue
        cached = cache_db.get(p, source_lang, target_lang)
        if cached is not None:
            results[i] = cached
        else:
            missing_indices.append(i)

    completed_count = total - len(missing_indices)
    if progress_callback:
        progress_callback(completed_count, total, "Verificando progresso salvo no cache...")

    if not missing_indices:
        return [r or "" for r in results]

    # 2. Agrupa parágrafos pendentes em lotes de até MAX_CHARS_GOOGLE caracteres
    batches: List[List[int]] = []
    current_batch: List[int] = []
    current_len = 0

    for idx in missing_indices:
        p_text = paragraphs[idx].strip().replace("\n", " ")
        p_len = len(p_text)
        sep_len = 2 if current_batch else 0
        if current_batch and (current_len + sep_len + p_len > MAX_CHARS_GOOGLE or len(current_batch) >= 18):
            batches.append(current_batch)
            current_batch = [idx]
            current_len = p_len
        else:
            current_batch.append(idx)
            current_len += sep_len + p_len

    if current_batch:
        batches.append(current_batch)

    last_req_time = 0.0

    def _pace_request() -> None:
        nonlocal last_req_time
        elapsed = time.monotonic() - last_req_time
        if elapsed < min_request_interval:
            time.sleep(min_request_interval - elapsed)
        last_req_time = time.monotonic()

    # 3. Traduz cada lote e salva imediatamente no SQLite
    for batch_num, batch_indices in enumerate(batches, start=1):
        if cancel_check and cancel_check():
            break

        if len(batch_indices) == 1:
            idx = batch_indices[0]
            orig_text = paragraphs[idx].strip()
            _pace_request()
            trans_text, _ = google_translate(orig_text, target_lang, source_lang)
            results[idx] = trans_text
            cache_db.put(orig_text, trans_text, source_lang, target_lang)
            completed_count += 1
            if progress_callback:
                progress_callback(completed_count, total, trans_text[:80])
            continue

        # Prepara texto unido por quebra dupla
        normalized_originals = [
            re.sub(r"\s+", " ", paragraphs[idx]).strip() for idx in batch_indices
        ]
        joined_payload = "\n\n".join(normalized_originals)

        _pace_request()
        translated_payload, _ = google_translate(joined_payload, target_lang, source_lang)
        split_parts = [part.strip() for part in translated_payload.split("\n\n") if part.strip()]

        if len(split_parts) == len(batch_indices):
            pairs_to_save = []
            for idx, part in zip(batch_indices, split_parts):
                results[idx] = part
                pairs_to_save.append((paragraphs[idx], part))
            cache_db.put_many(pairs_to_save, source_lang, target_lang)
            completed_count += len(batch_indices)
            if progress_callback:
                progress_callback(completed_count, total, split_parts[-1][:80])
        else:
            # Fallback seguro: traduz parágrafo por parágrafo se o lote fundiu/dividiu alguma linha
            for idx in batch_indices:
                if cancel_check and cancel_check():
                    break
                orig_text = paragraphs[idx].strip()
                _pace_request()
                trans_text, _ = google_translate(orig_text, target_lang, source_lang)
                results[idx] = trans_text
                cache_db.put(orig_text, trans_text, source_lang, target_lang)
                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count, total, trans_text[:80])

    return [r if r is not None else paragraphs[i] for i, r in enumerate(results)]
