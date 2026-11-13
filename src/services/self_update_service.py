# Role: service
"""Serviço de aplicação que orquestra verificação, download validado e disparo de atualização."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from typing import Callable, Optional

from src.adapters.github_release_client import download_release_archive, fetch_latest_manifest
from src.adapters.windows_swap_installer import launch_trampoline_installer, stage_update_zip
from src.domain.update_models import (
    DevelopmentModeUpdateError,
    ReleaseManifest,
    StagedUpdate,
    UpdateCheckResult,
)
from src.domain.version import APP_VERSION, LATEST_MANIFEST_URL
from src.policies.semver_policy import is_newer_version


def check_for_updates(
    current_version: str = APP_VERSION,
    manifest_url: str = LATEST_MANIFEST_URL,
    fetch_fn: Callable[[str], ReleaseManifest] = fetch_latest_manifest,
) -> UpdateCheckResult:
    """Consulta o manifesto remoto de forma resiliente sem propagar exceções de rede."""
    try:
        manifest = fetch_fn(manifest_url)
        has_newer = is_newer_version(current_version, manifest.version)
        return UpdateCheckResult(
            current_version=current_version,
            update_available=has_newer,
            manifest=manifest,
            error_message=None,
        )
    except Exception as exc:
        return UpdateCheckResult(
            current_version=current_version,
            update_available=False,
            manifest=None,
            error_message=str(exc),
        )


def prepare_and_stage_update(
    manifest: ReleaseManifest,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    is_frozen: Optional[bool] = None,
    download_fn: Callable[..., str] = download_release_archive,
) -> StagedUpdate:
    """Baixa, verifica integridade e descompacta a nova versão em diretório temporário."""
    frozen_mode = getattr(sys, "frozen", False) if is_frozen is None else is_frozen
    if not frozen_mode:
        raise DevelopmentModeUpdateError(
            "Atualização automática disponível apenas no executável compilado (TradutorLivros.exe). "
            "Em código-fonte, use 'git pull'."
        )

    staging_root = tempfile.mkdtemp(prefix="tradutor_livros_upd_")
    zip_dest = os.path.join(staging_root, manifest.asset_name or "update.zip")
    try:
        download_fn(
            manifest,
            zip_dest,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        return stage_update_zip(zip_dest, staging_root, manifest)
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise


def trigger_update_and_exit_ready(
    staged: StagedUpdate,
    target_app_dir: Optional[str] = None,
    relaunch: bool = True,
) -> str:
    """Aciona o instalador trampolim que substituirá os binários após o processo encerrar."""
    app_dir = target_app_dir or os.path.dirname(os.path.abspath(sys.executable))
    return launch_trampoline_installer(
        staged=staged,
        target_app_dir=app_dir,
        current_pid=os.getpid(),
        relaunch=relaunch,
    )
