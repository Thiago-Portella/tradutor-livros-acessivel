# Role: controller
"""Gera TradutorLivros-win64.zip e manifesto latest.json validado para GitHub Releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.domain.version import APP_VERSION, GITHUB_REPO, RELEASE_ASSET_NAME
from src.policies.semver_policy import parse_and_validate_manifest, parse_semver


def _compute_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def build_release_assets(
    tag: str,
    repo: str,
    dist_dir: Path,
    out_dir: Path,
    release_notes: str = "",
) -> tuple[Path, Path]:
    """Empacota dist_dir em ZIP portátil e gera latest.json validado contra a tag."""
    normalized_tag = tag.strip()
    tag_semver = parse_semver(normalized_tag)
    app_semver = parse_semver(APP_VERSION)
    if tag_semver != app_semver:
        raise ValueError(
            f"Tag {normalized_tag!r} diverge de APP_VERSION ({APP_VERSION!r}) em src/domain/version.py."
        )

    exe_path = dist_dir / "TradutorLivros.exe"
    if not exe_path.is_file():
        raise FileNotFoundError(f"Executável ausente em dist_dir: {exe_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / RELEASE_ASSET_NAME
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in sorted(dist_dir.rglob("*")):
            if item.is_file():
                arc_name = Path("TradutorLivros") / item.relative_to(dist_dir)
                zf.write(item, arc_name.as_posix())

    sha256_hex = _compute_sha256(zip_path)
    size_bytes = zip_path.stat().st_size
    version_str = ".".join(str(x) for x in tag_semver)
    manifest_obj = {
        "version": version_str,
        "tag": normalized_tag,
        "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asset_name": RELEASE_ASSET_NAME,
        "download_url": f"https://github.com/{repo}/releases/download/{normalized_tag}/{RELEASE_ASSET_NAME}",
        "sha256": sha256_hex,
        "size_bytes": size_bytes,
        "release_notes": release_notes.strip(),
    }
    raw_manifest = json.dumps(manifest_obj, ensure_ascii=False, indent=2) + "\n"
    parse_and_validate_manifest(raw_manifest)

    manifest_path = out_dir / "latest.json"
    manifest_path.write_text(raw_manifest, encoding="utf-8")
    return zip_path, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera pacote ZIP portátil e latest.json para Release.")
    parser.add_argument("--tag", required=True, help="Tag da release no formato vX.Y.Z")
    parser.add_argument("--repo", default=GITHUB_REPO, help="Repositório owner/name no GitHub")
    parser.add_argument("--dist-dir", default=str(ROOT_DIR / "dist" / "TradutorLivros"))
    parser.add_argument("--out-dir", default=str(ROOT_DIR / "release_assets"))
    parser.add_argument("--notes-file", default="", help="Arquivo UTF-8 com notas da release")
    parser.add_argument("--notes", default="", help="Texto direto com notas da release")
    args = parser.parse_args()

    notes = args.notes
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8")

    try:
        zip_path, manifest_path = build_release_assets(
            tag=args.tag,
            repo=args.repo,
            dist_dir=Path(args.dist_dir),
            out_dir=Path(args.out_dir),
            release_notes=notes,
        )
    except Exception as exc:
        print(f"[release-assets] ERRO: {exc}", file=sys.stderr)
        return 1

    print(f"[release-assets] Pacote gerado: {zip_path}")
    print(f"[release-assets] Manifesto gerado: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
