# Role: adapter
"""Gravação atômica com temporário único e mensagem clara para arquivo bloqueado."""

from __future__ import annotations

import os
from typing import Callable

from src.domain.models import TranslationError
from src.policies.path_policy import make_unique_temp_path


def write_atomically(
    output_path: str,
    writer_fn: Callable[[str], None],
    temp_prefix: str = ".tmp_export",
) -> str:
    """Executa gravação em arquivo temporário único e substitui o destino com limpeza segura."""
    abs_out = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_out), exist_ok=True)
    tmp_path = make_unique_temp_path(abs_out, prefix=temp_prefix)
    try:
        writer_fn(tmp_path)
        os.replace(tmp_path, abs_out)
        return abs_out
    except PermissionError as e:
        raise TranslationError(
            f"Não foi possível salvar em '{abs_out}' porque o arquivo está aberto em outro programa. "
            "Feche o leitor de PDF/EPUB e tente novamente."
        ) from e
    except OSError as e:
        raise TranslationError(
            f"Falha ao gravar o arquivo de saída '{abs_out}': {e}"
        ) from e
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
