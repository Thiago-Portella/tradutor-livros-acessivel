# Role: controller
"""Instrumento de voo único do repositório (doctor, build --if-stale e check)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.arch_checks import (
    check_architecture_sync,
    check_comment_hygiene,
    check_forbidden_filenames,
    check_line_limits,
    check_roles,
    iter_project_py_files,
)


def cmd_doctor() -> int:
    print("[doctor] Verificando dependências Python e estrutura...")
    for mod in ("wx", "pymupdf", "sqlite3", "PyInstaller"):
        try:
            __import__(mod)
        except Exception as e:
            print(f"[doctor] FALHA ao importar '{mod}': {e}", file=sys.stderr)
            return 1
    for req_dir in (ROOT_DIR / "specs", ROOT_DIR / "docs", ROOT_DIR / "src", ROOT_DIR / "tests"):
        if not req_dir.exists():
            print(f"[doctor] FALHA: diretório obrigatório ausente: {req_dir}", file=sys.stderr)
            return 1
    print("[doctor] Ambiente íntegro.")
    return 0


def _is_exe_stale() -> bool:
    exe_path = ROOT_DIR / "dist" / "TradutorLivros" / "TradutorLivros.exe"
    if not exe_path.exists():
        return True
    exe_mtime = exe_path.stat().st_mtime
    watch_files = [
        p for p in iter_project_py_files(ROOT_DIR, include_tests=False) if p.relative_to(ROOT_DIR).parts[0] != "tools"
    ] + [ROOT_DIR / "TradutorLivros.spec"]
    return any(p.exists() and p.stat().st_mtime > exe_mtime for p in watch_files)


def cmd_build(if_stale: bool = True) -> int:
    if if_stale and not _is_exe_stale():
        print("[build] TradutorLivros.exe atualizado (nenhum fonte mais recente).")
        return 0
    print("[build] Recompilando TradutorLivros.exe via PyInstaller...")
    subprocess.run(
        ["taskkill", "/F", "/IM", "TradutorLivros.exe"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    proc = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(ROOT_DIR / "TradutorLivros.spec")],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode
    exe_path = ROOT_DIR / "dist" / "TradutorLivros" / "TradutorLivros.exe"
    if not exe_path.exists():
        print("[build] FALHA: TradutorLivros.exe não encontrado após build.", file=sys.stderr)
        return 1
    print(f"[build] Executável gerado com sucesso: {exe_path}")
    return 0


def run_all_tests() -> int:
    print("[tests] Executando 100% da suíte automatizada...")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT_DIR)
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT_DIR / "tests"), "-p", "test_*.py", "-v"],
        cwd=str(ROOT_DIR),
        env=env,
    )
    return proc.returncode


def cmd_check() -> int:
    if cmd_doctor() != 0:
        return 1

    print("[lint] Verificando invariantes arquiteturais...")
    lint_errors = (
        check_roles(ROOT_DIR)
        + check_line_limits(ROOT_DIR)
        + check_forbidden_filenames(ROOT_DIR)
        + check_comment_hygiene(ROOT_DIR)
        + check_architecture_sync(ROOT_DIR)
    )
    if lint_errors:
        for err in lint_errors:
            print(f"[lint] ERRO: {err}", file=sys.stderr)
        return 1
    print("[lint] Todos os invariantes arquiteturais aprovados.")

    if cmd_build(if_stale=True) != 0:
        return 1

    return run_all_tests()


def main() -> int:
    parser = argparse.ArgumentParser(description="Instrumento de voo único do projeto.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Verifica ambiente e estrutura")
    p_build = sub.add_parser("build", help="Compila TradutorLivros.exe")
    p_build.add_argument("--if-stale", action="store_true", help="Compila apenas se desatualizado")
    sub.add_parser("check", help="Executa doctor, linters, build --if-stale e todos os testes")

    args = parser.parse_args()
    if args.command == "doctor":
        return cmd_doctor()
    if args.command == "build":
        return cmd_build(if_stale=args.if_stale)
    return cmd_check()


if __name__ == "__main__":
    sys.exit(main())
