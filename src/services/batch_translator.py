# Role: service
"""Orquestrador de tradução em lote com cache SQLite e fallback 1:1."""

from __future__ import annotations

import re
import time
from typing import Callable, List, Optional

from src.adapters.google_translate_client import google_translate
from src.adapters.sqlite_cache import TranslationCacheDB
from src.policies.sentence_splitter import group_paragraphs_into_batches


def translate_paragraphs_batch(
    paragraphs: List[str],
    target_lang: str,
    source_lang: str,
    cache_db: TranslationCacheDB,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    min_request_interval: float = 0.25,
    detected_lang_sink: Optional[List[str]] = None,
) -> List[str]:
    """Traduz parágrafos em lote com fallback 1:1, cache SQLite WAL e captura de idioma detectado."""
    total = len(paragraphs)
    results: List[Optional[str]] = [None] * total
    missing_indices: List[int] = []

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

    batches = group_paragraphs_into_batches(paragraphs, missing_indices)
    last_req_time = 0.0

    def _pace() -> None:
        nonlocal last_req_time
        elapsed = time.monotonic() - last_req_time
        if elapsed < min_request_interval:
            time.sleep(min_request_interval - elapsed)
        last_req_time = time.monotonic()

    def _record_detected(det: str) -> None:
        if detected_lang_sink is not None and det and det != "auto" and not detected_lang_sink:
            detected_lang_sink.append(det)

    for batch_indices in batches:
        if cancel_check and cancel_check():
            break

        if len(batch_indices) == 1:
            idx = batch_indices[0]
            orig_text = paragraphs[idx].strip()
            _pace()
            trans_text, det = google_translate(orig_text, target_lang, source_lang)
            _record_detected(det)
            results[idx] = trans_text
            cache_db.put(orig_text, trans_text, source_lang, target_lang)
            completed_count += 1
            if progress_callback:
                progress_callback(completed_count, total, trans_text[:80])
            continue

        joined = "\n\n".join(re.sub(r"\s+", " ", paragraphs[idx]).strip() for idx in batch_indices)
        _pace()
        translated_payload, det = google_translate(joined, target_lang, source_lang)
        _record_detected(det)
        split_parts = [part.strip() for part in translated_payload.split("\n\n") if part.strip()]

        if len(split_parts) == len(batch_indices):
            pairs = []
            for idx, part in zip(batch_indices, split_parts):
                results[idx] = part
                pairs.append((paragraphs[idx], part))
            cache_db.put_many(pairs, source_lang, target_lang)
            completed_count += len(batch_indices)
            if progress_callback:
                progress_callback(completed_count, total, split_parts[-1][:80])
        else:
            for idx in batch_indices:
                if cancel_check and cancel_check():
                    break
                orig_text = paragraphs[idx].strip()
                _pace()
                trans_text, det_item = google_translate(orig_text, target_lang, source_lang)
                _record_detected(det_item)
                results[idx] = trans_text
                cache_db.put(orig_text, trans_text, source_lang, target_lang)
                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count, total, trans_text[:80])

    return [r if r is not None else paragraphs[i] for i, r in enumerate(results)]
