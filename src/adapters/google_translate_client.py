# Role: adapter
"""Cliente HTTP unitário do motor de tradução com SSL isolado e fatiamento longo."""

from __future__ import annotations

import json
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request as urllibRequest
from typing import List, Optional, Tuple

from src.domain.models import TranslationError, TranslationRateLimitError
from src.policies.sentence_splitter import split_long_paragraph
from src.policies.text_normalizer import clean_text_for_translate

GOOGLE_TRANSLATE_URL = "https://translate-pa.googleapis.com/v1/translate"
GOOGLE_TRANSLATE_CLIENT = "gtx"
_GOOGLE_TRANSLATE_KEY_PARTS = ("AIzaSyDLEeFI5OtFBwYBIoK_jj5", "m32rZK5CkCXA")
GOOGLE_TRANSLATE_API_KEY = "".join(_GOOGLE_TRANSLATE_KEY_PARTS)


def _create_opener(verify_ssl: bool = True) -> urllibRequest.OpenerDirector:
    # Mantém fallback SSL restrito a este opener sem alterar o contexto global do Python
    ctx = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()
    opener = urllibRequest.build_opener(urllibRequest.HTTPSHandler(context=ctx))
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


def _parse_google_response(data: object) -> Tuple[str, Optional[str]]:
    if not isinstance(data, list) or not data:
        return "", None
    sentences = data[1] if len(data) > 1 else None
    if sentences and isinstance(sentences, list):
        translation = "".join(s[0] for s in sentences if s and s[0])
    else:
        translation = data[0] or ""
    for zw in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"):
        translation = translation.replace(zw, "")
    detected = data[5] if len(data) > 5 and isinstance(data[5], str) and data[5] else None
    return translation, detected


def _request_single_chunk(
    cleaned_text: str,
    target_lang: str,
    source_lang: str,
    retry: int,
) -> Tuple[str, str]:
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
    opener = _create_opener(verify_ssl=True)

    base_delay, max_delay, max_wait = 0.6, 6.0, 45.0
    start_time = time.monotonic()

    for attempt in range(retry + 1):
        remaining = max_wait - (time.monotonic() - start_time)
        if remaining <= 0:
            raise TranslationError(f"Tempo limite de tradução excedido após {max_wait:.0f} segundos")
        attempt_timeout = min(15.0, remaining)
        delay = min(min(base_delay * (2**attempt), max_delay) + random.uniform(0.05, 0.35), remaining)
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
            if isinstance(getattr(e, "reason", None), ssl.SSLError):
                opener = _create_opener(verify_ssl=False)
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


def google_translate(
    text: str,
    target_lang: str = "pt",
    source_lang: str = "auto",
    retry: int = 4,
) -> Tuple[str, str]:
    """Traduz texto fatiando automaticamente parágrafos longos ou não-ASCII por sentenças."""
    if not text or not text.strip():
        return text, source_lang

    cleaned_text = clean_text_for_translate(text)
    if not cleaned_text:
        return text, source_lang

    chunks = split_long_paragraph(cleaned_text)
    if len(chunks) <= 1:
        return _request_single_chunk(cleaned_text, target_lang, source_lang, retry)

    translated_chunks: List[str] = []
    detected_final = source_lang
    for chunk in chunks:
        trans_part, detected_part = _request_single_chunk(chunk, target_lang, source_lang, retry)
        translated_chunks.append(trans_part.strip())
        if detected_part and detected_part != "auto":
            detected_final = detected_part
    return " ".join(translated_chunks).strip(), detected_final
