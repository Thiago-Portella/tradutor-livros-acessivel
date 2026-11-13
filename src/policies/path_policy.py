# Role: policy
"""Políticas de validação de intervalo de páginas/seções e caminhos seguros no Windows."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from typing import Optional

from src.domain.models import SUPPORTED_FORMATS


def validate_page_bounds(
    start_page: Optional[int],
    end_page: Optional[int],
) -> None:
    """Valida se os limites de página/capítulo são positivos e coerentes."""
    if start_page is not None and start_page < 1:
        raise ValueError("A página/seção inicial deve ser maior ou igual a 1.")
    if end_page is not None and end_page < 1:
        raise ValueError("A página/seção final deve ser maior ou igual a 1.")
    if start_page is not None and end_page is not None and start_page > end_page:
        raise ValueError(
            f"Intervalo inválido: a página inicial ({start_page}) não pode ser maior que a página final ({end_page})."
        )


def get_default_cache_path(input_file: str) -> str:
    """Retorna o caminho do banco SQLite respeitando o limite MAX_PATH do Windows."""
    abs_input = os.path.abspath(input_file)
    base_dir = os.path.dirname(abs_input)
    base_name = os.path.splitext(os.path.basename(abs_input))[0]

    legacy_cache = os.path.join(base_dir, f".{base_name}_translation_cache.sqlite3")
    try:
        if os.path.exists(legacy_cache):
            if os.path.getsize(legacy_cache) == 0:
                os.remove(legacy_cache)
            elif len(legacy_cache) <= 215:
                return legacy_cache
    except OSError:
        pass

    short_hash = hashlib.sha256(abs_input.lower().encode("utf-8")).hexdigest()[:12]
    safe_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", base_name).strip("_")[:36] or "livro"

    fallback_dir = os.path.join(os.path.expanduser("~"), ".tradutor_livros_cache")
    os.makedirs(fallback_dir, exist_ok=True)
    return os.path.join(fallback_dir, f"{safe_prefix}_{short_hash}_cache.sqlite3")


def clamp_output_path_length(dir_path: str, base_name: str, ext: str, suffix: str = "") -> str:
    max_total = 230
    avail = max(25, max_total - len(dir_path) - 1 - len(suffix) - len(ext))
    trimmed_base = base_name[:avail].rstrip(" ._-") if len(base_name) > avail else base_name
    return os.path.join(dir_path, f"{trimmed_base}{suffix}{ext}")


def _resolve_extension(output_format: str) -> str:
    fmt_key = output_format.lower().lstrip(".")
    if fmt_key == "markdown":
        fmt_key = "md"
    return SUPPORTED_FORMATS.get(fmt_key, ("", f".{fmt_key}"))[1]


def get_default_output_path(
    input_file: str,
    target_lang: str = "pt",
    output_format: str = "epub",
    bilingual: bool = False,
    enhance_only: bool = False,
) -> str:
    abs_input = os.path.abspath(input_file)
    base_dir = os.path.dirname(abs_input)
    base_name = os.path.splitext(os.path.basename(abs_input))[0]
    ext = _resolve_extension(output_format)

    docs_dir = os.path.join(os.path.expanduser("~"), "Documents", "Livros_Processados")
    candidate = clamp_output_path_length(base_dir, base_name, ext)

    if os.path.abspath(candidate).lower() == abs_input.lower():
        try:
            os.makedirs(docs_dir, exist_ok=True)
            docs_candidate = clamp_output_path_length(docs_dir, base_name, ext)
            if os.path.abspath(docs_candidate).lower() != abs_input.lower():
                return docs_candidate
            suffix = "_aprimorado" if enhance_only else f"_{target_lang}"
            return clamp_output_path_length(docs_dir, base_name, ext, suffix=suffix)
        except OSError:
            suffix = "_aprimorado" if enhance_only else f"_{target_lang}"
            return clamp_output_path_length(base_dir, base_name, ext, suffix=suffix)

    probe_file = os.path.join(base_dir, f".write_test_{os.getpid()}_{uuid.uuid4().hex[:6]}")
    try:
        with open(probe_file, "w"):
            pass
        os.remove(probe_file)
        return candidate
    except OSError:
        try:
            os.makedirs(docs_dir, exist_ok=True)
            return clamp_output_path_length(docs_dir, base_name, ext)
        except OSError:
            return clamp_output_path_length(os.getcwd(), base_name, ext)


def ensure_safe_output_path(
    input_path: str,
    output_path: str,
    output_format: str = "epub",
    target_lang: str = "pt",
    enhance_only: bool = False,
) -> str:
    """Garante que a saída não sobrescreva a entrada nem exceda MAX_PATH."""
    abs_in = os.path.abspath(input_path)
    abs_out = os.path.abspath(output_path)
    out_dir = os.path.dirname(abs_out)
    out_base, out_ext = os.path.splitext(os.path.basename(abs_out))
    if not out_ext:
        out_ext = _resolve_extension(output_format)

    if abs_out.lower() == abs_in.lower():
        return get_default_output_path(
            input_path,
            target_lang=target_lang,
            output_format=output_format,
            enhance_only=enhance_only,
        )
    if len(abs_out) > 235:
        return clamp_output_path_length(out_dir, out_base, out_ext)
    return abs_out


def make_partial_output_path(output_path: str) -> str:
    """Gera o caminho <nome>_parcial.<ext> respeitando o limite de tamanho no Windows."""
    abs_out = os.path.abspath(output_path)
    out_dir = os.path.dirname(abs_out)
    out_base, out_ext = os.path.splitext(os.path.basename(abs_out))
    if out_base.endswith("_parcial"):
        return clamp_output_path_length(out_dir, out_base, out_ext)
    return clamp_output_path_length(out_dir, out_base, out_ext, suffix="_parcial")


def make_unique_temp_path(output_path: str, prefix: str = ".tmp_export") -> str:
    """Gera nome temporário exclusivo por processo e execução no mesmo diretório de destino."""
    abs_out = os.path.abspath(output_path)
    out_dir = os.path.dirname(abs_out)
    _, out_ext = os.path.splitext(abs_out)
    token = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
    return os.path.join(out_dir, f"{prefix}_{token}{out_ext or '.tmp'}")
