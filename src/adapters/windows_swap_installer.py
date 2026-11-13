# Role: adapter
"""Descompactação validada em staging e script trampolim .cmd para troca segura no Windows."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from src.domain.update_models import ReleaseManifest, StagedUpdate, UpdateError
from src.policies.semver_policy import validate_zip_member_paths


def stage_update_zip(
    zip_path: str,
    staging_root: str,
    manifest: ReleaseManifest,
) -> StagedUpdate:
    """Valida todas as entradas do ZIP contra Zip Slip antes de extrair para staging."""
    extracted_root = Path(staging_root) / "extracted"
    if extracted_root.exists():
        shutil.rmtree(extracted_root, ignore_errors=True)
    extracted_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        validate_zip_member_paths(zf.namelist())
        zf.extractall(extracted_root)

    direct_exe = extracted_root / "TradutorLivros.exe"
    nested_dir = extracted_root / "TradutorLivros"
    nested_exe = nested_dir / "TradutorLivros.exe"

    if nested_exe.is_file():
        app_dir = nested_dir
    elif direct_exe.is_file():
        app_dir = extracted_root
    else:
        raise UpdateError("Pacote ZIP inválido: executável TradutorLivros.exe não encontrado.")

    return StagedUpdate(
        staging_dir=str(Path(staging_root).resolve()),
        extracted_app_dir=str(app_dir.resolve()),
        manifest=manifest,
    )


def build_trampoline_batch_content(
    pid: int,
    source_app_dir: str,
    target_app_dir: str,
    exe_name: str = "TradutorLivros.exe",
    relaunch: bool = True,
    staging_dir: str = "",
) -> str:
    """Gera roteiro .cmd para aguardar PID encerrar, atualizar pasta e relançar o aplicativo."""
    src_norm = os.path.normpath(source_app_dir)
    dst_norm = os.path.normpath(target_app_dir)
    stage_norm = os.path.normpath(staging_dir or os.path.dirname(src_norm))
    exe_target = os.path.join(dst_norm, exe_name)

    lines = [
        "@echo off",
        "chcp 65001 >nul",
        f'set "SRC={src_norm}"',
        f'set "DST={dst_norm}"',
        f'set "STAGE={stage_norm}"',
        f"set /a WAIT_COUNT=0",
        ":wait_pid",
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul',
        "if not errorlevel 1 (",
        "    if %WAIT_COUNT% GEQ 30 goto apply_files",
        "    set /a WAIT_COUNT+=1",
        "    timeout /t 1 /nobreak >nul",
        "    goto wait_pid",
        ")",
        ":apply_files",
        'robocopy "%SRC%" "%DST%" /E /IS /IT /R:5 /W:1 /NFL /NDL /NJH /NJS >nul',
        'if exist "%SRC%\\_internal" (',
        '    robocopy "%SRC%\\_internal" "%DST%\\_internal" /MIR /R:5 /W:1 /NFL /NDL /NJH /NJS >nul',
        ")",
    ]
    if relaunch:
        lines.append(f'start "" "{exe_target}"')
    lines.extend(
        [
            'if exist "%STAGE%" rmdir /s /q "%STAGE%" >nul 2>&1',
            '(goto) 2>nul & del "%~f0"',
        ]
    )
    return "\r\n".join(lines) + "\r\n"


def launch_trampoline_installer(
    staged: StagedUpdate,
    target_app_dir: str,
    current_pid: int,
    relaunch: bool = True,
) -> str:
    """Grava e dispara o script trampolim .cmd em processo destacado fora da pasta alvo."""
    fd, script_path = tempfile.mkstemp(prefix="tradutor_livros_apply_", suffix=".cmd")
    os.close(fd)
    content = build_trampoline_batch_content(
        pid=current_pid,
        source_app_dir=staged.extracted_app_dir,
        target_app_dir=target_app_dir,
        relaunch=relaunch,
        staging_dir=staged.staging_dir,
    )
    with open(script_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)

    creation_flags = 0
    for flag_name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        creation_flags |= getattr(subprocess, flag_name, 0)

    subprocess.Popen(
        ["cmd.exe", "/c", script_path],
        creationflags=creation_flags,
        close_fds=True,
    )
    return script_path
