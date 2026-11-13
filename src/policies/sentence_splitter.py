# Role: policy
"""Fatiamento determinístico de parágrafos longos por sentenças e orçamento URL."""

from __future__ import annotations

import re
import urllib.parse
from typing import List

MAX_CHARS_PER_CHUNK = 3600
MAX_ENCODED_BYTES_PER_CHUNK = 10500
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…।！？])\s+")
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[;:,])\s+|\n+")


def measure_encoded_len(text: str) -> int:
    return len(urllib.parse.quote(text, safe=""))


def _fits_budget(text: str, max_chars: int, max_encoded_bytes: int) -> bool:
    return len(text) <= max_chars and measure_encoded_len(text) <= max_encoded_bytes


def _split_piece_hard(text: str, max_chars: int, max_encoded_bytes: int) -> List[str]:
    words = text.split(" ")
    chunks: List[str] = []
    curr = ""
    for word in words:
        cand = f"{curr} {word}".strip() if curr else word
        if _fits_budget(cand, max_chars, max_encoded_bytes):
            curr = cand
            continue
        if curr:
            chunks.append(curr)
            curr = ""
        if _fits_budget(word, max_chars, max_encoded_bytes):
            curr = word
            continue
        # Quebra caractere a caractere apenas quando uma palavra isolada excede o limite HTTP
        sub = ""
        for ch in word:
            if _fits_budget(sub + ch, max_chars, max_encoded_bytes):
                sub += ch
            else:
                if sub:
                    chunks.append(sub)
                sub = ch
        curr = sub
    if curr:
        chunks.append(curr)
    return chunks


def _pack_fragments(fragments: List[str], max_chars: int, max_encoded_bytes: int, fallback_split: bool) -> List[str]:
    chunks: List[str] = []
    curr = ""
    for frag in fragments:
        frag_s = frag.strip()
        if not frag_s:
            continue
        cand = f"{curr} {frag_s}".strip() if curr else frag_s
        if _fits_budget(cand, max_chars, max_encoded_bytes):
            curr = cand
            continue
        if curr:
            chunks.append(curr)
            curr = ""
        if _fits_budget(frag_s, max_chars, max_encoded_bytes):
            curr = frag_s
        elif fallback_split:
            clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(frag_s) if c.strip()]
            if len(clauses) > 1:
                chunks.extend(_pack_fragments(clauses, max_chars, max_encoded_bytes, False))
            else:
                chunks.extend(_split_piece_hard(frag_s, max_chars, max_encoded_bytes))
        else:
            chunks.extend(_split_piece_hard(frag_s, max_chars, max_encoded_bytes))
    if curr:
        chunks.append(curr)
    return chunks


def split_long_paragraph(
    text: str,
    max_chars: int = MAX_CHARS_PER_CHUNK,
    max_encoded_bytes: int = MAX_ENCODED_BYTES_PER_CHUNK,
) -> List[str]:
    """Divide parágrafo que exceda limite de caracteres ou de bytes URL-encoded."""
    stripped = (text or "").strip()
    if not stripped or _fits_budget(stripped, max_chars, max_encoded_bytes):
        return [stripped] if stripped else []
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(stripped) if s.strip()]
    if len(sentences) <= 1:
        clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(stripped) if c.strip()]
        if len(clauses) > 1:
            return _pack_fragments(clauses, max_chars, max_encoded_bytes, False)
        return _split_piece_hard(stripped, max_chars, max_encoded_bytes)
    return _pack_fragments(sentences, max_chars, max_encoded_bytes, True)


def group_paragraphs_into_batches(
    paragraphs: List[str],
    indices: List[int],
    max_chars: int = MAX_CHARS_PER_CHUNK,
    max_encoded_bytes: int = MAX_ENCODED_BYTES_PER_CHUNK,
    max_items: int = 16,
) -> List[List[int]]:
    """Agrupa parágrafos em lotes dentro do orçamento de caracteres e bytes URL-encoded."""
    batches: List[List[int]] = []
    current_batch: List[int] = []
    current_chars = 0
    current_bytes = 0
    sep_encoded = measure_encoded_len("\n\n")

    for idx in indices:
        p_norm = re.sub(r"\s+", " ", paragraphs[idx]).strip()
        p_chars = len(p_norm)
        p_bytes = measure_encoded_len(p_norm)

        if not _fits_budget(p_norm, max_chars, max_encoded_bytes):
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
                current_bytes = 0
            batches.append([idx])
            continue

        sep_c = 2 if current_batch else 0
        sep_b = sep_encoded if current_batch else 0
        if current_batch and (
            current_chars + sep_c + p_chars > max_chars
            or current_bytes + sep_b + p_bytes > max_encoded_bytes
            or len(current_batch) >= max_items
        ):
            batches.append(current_batch)
            current_batch = [idx]
            current_chars = p_chars
            current_bytes = p_bytes
        else:
            current_batch.append(idx)
            current_chars += sep_c + p_chars
            current_bytes += sep_b + p_bytes

    if current_batch:
        batches.append(current_batch)
    return batches
