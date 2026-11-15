# Role: service
"""Serviço de geração atômica e abertura do Manual do Usuário HTML5 no navegador."""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from typing import Callable, Optional

from src.adapters.atomic_file_writer import write_atomically
from src.policies.user_manual_content import render_user_manual_html


def get_default_manual_path() -> str:
    """Retorna o caminho padrão seguro e gravável para o manual HTML5 do usuário."""
    manual_dir = os.path.join(os.path.expanduser("~"), ".tradutor_livros_cache")
    os.makedirs(manual_dir, exist_ok=True)
    return os.path.join(manual_dir, "manual_usuario.html")


def generate_user_manual_html(output_path: Optional[str] = None) -> str:
    """Gera e grava atomicamente o Manual Completo do Usuário em HTML5 acessível."""
    target_path = os.path.abspath(output_path) if output_path else get_default_manual_path()
    parent_dir = os.path.dirname(target_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    html_content = render_user_manual_html()

    def _write(tmp_path: str) -> None:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(html_content)

    return write_atomically(target_path, _write, temp_prefix=".tmp_manual")


def open_user_manual(
    output_path: Optional[str] = None,
    browser_opener: Optional[Callable[[str], object]] = None,
) -> str:
    """Gera o manual HTML5 atualizado e abre sua URI local diretamente no navegador."""
    html_path = generate_user_manual_html(output_path)
    uri = Path(html_path).resolve().as_uri()
    opener = browser_opener if browser_opener is not None else webbrowser.open
    opened = opener(uri)
    if opened is False:
        raise RuntimeError(f"Não foi possível acionar o navegador para abrir '{html_path}'.")
    return html_path
