# Role: value
"""Modelos imutáveis e exceções tipadas do fluxo de atualização interna."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class UpdateError(Exception):
    """Erro base para falhas controladas durante verificação ou atualização."""


class IntegrityVerificationError(UpdateError):
    """Lançada quando o hash SHA-256 do pacote baixado diverge do manifesto."""


class UnsafeArchiveError(UpdateError):
    """Lançada quando o pacote compactado contém caminhos inseguros fora da pasta alvo."""


class DevelopmentModeUpdateError(UpdateError):
    """Lançada ao tentar aplicar atualização binária sobre código-fonte em desenvolvimento."""


@dataclass(frozen=True)
class ReleaseManifest:
    version: str
    tag: str
    published_at: str
    asset_name: str
    download_url: str
    sha256: str
    size_bytes: int
    release_notes: str


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    update_available: bool
    manifest: Optional[ReleaseManifest] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class StagedUpdate:
    staging_dir: str
    extracted_app_dir: str
    manifest: ReleaseManifest
