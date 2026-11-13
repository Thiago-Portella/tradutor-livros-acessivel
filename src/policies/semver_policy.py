# Role: policy
"""Políticas puras de versionamento semântico, validação de manifesto e proteção Zip Slip."""

from __future__ import annotations

import json
import posixpath
import re
from typing import Iterable, Tuple

from src.domain.update_models import ReleaseManifest, UnsafeArchiveError, UpdateError

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:")


def parse_semver(version_str: str) -> Tuple[int, int, int]:
    """Converte string SemVer X.Y.Z ou vX.Y.Z em tupla numérica comparável."""
    if not isinstance(version_str, str):
        raise ValueError("Versão inválida: tipo não textual.")
    match = _SEMVER_RE.match(version_str.strip())
    if not match:
        raise ValueError(f"Versão SemVer inválida: {version_str!r}. Esperado formato X.Y.Z.")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_newer_version(current_version: str, candidate_version: str) -> bool:
    """Retorna True somente quando candidate_version é estritamente maior que current_version."""
    return parse_semver(candidate_version) > parse_semver(current_version)


def parse_and_validate_manifest(raw_json: str) -> ReleaseManifest:
    """Valida contrato estrito do arquivo latest.json antes de qualquer download."""
    try:
        data = json.loads(raw_json)
    except Exception as exc:
        raise UpdateError(f"Manifesto latest.json inválido: {exc}") from exc

    if not isinstance(data, dict):
        raise UpdateError("Manifesto latest.json deve ser um objeto JSON.")

    required_text = ("version", "tag", "asset_name", "download_url", "sha256")
    for field in required_text:
        val = data.get(field)
        if not isinstance(val, str) or not val.strip():
            raise UpdateError(f"Campo obrigatório ausente ou vazio no manifesto: {field}.")

    version_str = data["version"].strip().lstrip("v")
    try:
        parse_semver(version_str)
    except ValueError as exc:
        raise UpdateError(str(exc)) from exc

    download_url = data["download_url"].strip()
    if not download_url.startswith("https://"):
        raise UpdateError("URL de download do manifesto deve usar HTTPS.")

    sha256_norm = data["sha256"].strip().lower()
    if not _SHA256_RE.match(sha256_norm):
        raise UpdateError("Hash SHA-256 inválido no manifesto (esperados 64 hexadecimais).")

    raw_size = data.get("size_bytes", 0)
    if not isinstance(raw_size, int) or raw_size < 0:
        raise UpdateError("Campo size_bytes do manifesto deve ser inteiro não negativo.")

    published_at = str(data.get("published_at") or "").strip()
    release_notes = str(data.get("release_notes") or "")

    return ReleaseManifest(
        version=version_str,
        tag=data["tag"].strip(),
        published_at=published_at,
        asset_name=data["asset_name"].strip(),
        download_url=download_url,
        sha256=sha256_norm,
        size_bytes=raw_size,
        release_notes=release_notes,
    )


def validate_zip_member_paths(member_names: Iterable[str]) -> None:
    """Rejeita caminhos absolutos, letras de unidade Windows ou travessia '..' em ZIPs."""
    for raw_name in member_names:
        normalized = raw_name.replace("\\", "/")
        if not normalized or normalized.startswith("/") or _DRIVE_PREFIX_RE.match(normalized):
            raise UnsafeArchiveError(f"Entrada absoluta proibida no pacote: {raw_name!r}")
        cleaned = posixpath.normpath(normalized.rstrip("/"))
        parts = cleaned.split("/")
        if cleaned == ".." or ".." in parts:
            raise UnsafeArchiveError(f"Travessia de diretório detectada no pacote: {raw_name!r}")
