# Role: adapter
"""Cliente HTTP em biblioteca padrão para baixar manifesto latest.json e pacote ZIP do GitHub."""

from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from typing import Callable, Optional

from src.domain.update_models import IntegrityVerificationError, ReleaseManifest, UpdateError
from src.domain.version import APP_VERSION, LATEST_MANIFEST_URL
from src.policies.semver_policy import parse_and_validate_manifest

_CHUNK_BYTES = 65536
_MAX_MANIFEST_BYTES = 262144


def _build_request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": f"TradutorLivros-Updater/{APP_VERSION}",
            "Accept": "application/json, application/octet-stream, */*",
        },
    )


def fetch_latest_manifest(
    manifest_url: str = LATEST_MANIFEST_URL,
    timeout: float = 10.0,
) -> ReleaseManifest:
    """Obtém e valida o manifesto latest.json diretamente dos assets públicos de Release."""
    req = _build_request(manifest_url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read(_MAX_MANIFEST_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(
                "Nenhuma publicação com manifesto latest.json foi encontrada ainda no GitHub."
            ) from exc
        raise UpdateError(f"Erro HTTP {exc.code} ao consultar atualizações.") from exc
    except urllib.error.URLError as exc:
        raise UpdateError(f"Não foi possível conectar ao GitHub: {exc.reason}") from exc
    except Exception as exc:
        raise UpdateError(f"Falha ao consultar atualizações: {exc}") from exc

    if len(raw_bytes) > _MAX_MANIFEST_BYTES:
        raise UpdateError("Manifesto latest.json excede o tamanho máximo permitido.")

    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UpdateError("Manifesto latest.json não está codificado em UTF-8 válido.") from exc

    return parse_and_validate_manifest(raw_text)


def _safe_remove_file(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def download_release_archive(
    manifest: ReleaseManifest,
    dest_zip_path: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    timeout: float = 30.0,
) -> str:
    """Baixa o pacote ZIP em streaming validando tamanho, cancelamento e SHA-256."""
    dest_dir = os.path.dirname(os.path.abspath(dest_zip_path))
    os.makedirs(dest_dir, exist_ok=True)
    req = _build_request(manifest.download_url)
    hasher = hashlib.sha256()
    downloaded = 0

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest_zip_path, "wb") as fh:
            header_len = resp.headers.get("Content-Length")
            total_bytes = manifest.size_bytes or (
                int(header_len) if header_len and header_len.isdigit() else 0
            )
            while True:
                if cancel_check and cancel_check():
                    raise UpdateError("Download cancelado pelo usuário.")
                chunk = resp.read(_CHUNK_BYTES)
                if not chunk:
                    break
                fh.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total_bytes)
    except UpdateError:
        _safe_remove_file(dest_zip_path)
        raise
    except urllib.error.HTTPError as exc:
        _safe_remove_file(dest_zip_path)
        raise UpdateError(f"Erro HTTP {exc.code} ao baixar pacote de atualização.") from exc
    except urllib.error.URLError as exc:
        _safe_remove_file(dest_zip_path)
        raise UpdateError(f"Erro de rede durante o download: {exc.reason}") from exc
    except Exception as exc:
        _safe_remove_file(dest_zip_path)
        raise UpdateError(f"Falha ao gravar pacote de atualização: {exc}") from exc

    digest = hasher.hexdigest().lower()
    if digest != manifest.sha256.lower():
        _safe_remove_file(dest_zip_path)
        raise IntegrityVerificationError(
            "Falha de integridade SHA-256: o pacote baixado não confere com o manifesto oficial."
        )
    return dest_zip_path
