# Role: controller
"""Ponto de entrada CLI/GUI do Tradutor e Aprimorador Acessível de Livros."""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from typing import Optional

from src.controllers.gui_frame import run_gui
from src.domain.models import EnhancementOptions, FOOTNOTE_MODES
from src.domain.update_models import DevelopmentModeUpdateError
from src.domain.version import APP_NAME, APP_VERSION
from src.policies.path_policy import get_default_cache_path, get_default_output_path
from src.services.book_pipeline import enhance_only_book_pipeline, translate_book_pipeline
from src.services.self_update_service import (
    check_for_updates,
    prepare_and_stage_update,
    trigger_update_and_exit_ready,
)


def _attach_or_protect_stdio() -> None:
    """Garante fluxos stdout/stderr válidos mesmo quando compilado com console=False."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    attached = False
    if os.name == "nt":
        try:
            import ctypes

            if ctypes.windll.kernel32.AttachConsole(-1):
                attached = True
        except Exception:
            attached = False
    if attached:
        try:
            if sys.stdout is None:
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
            if sys.stderr is None:
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
            return
        except OSError:
            pass
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()


def run_cli(args: argparse.Namespace) -> int:
    _attach_or_protect_stdio()
    input_path = os.path.abspath(args.input)
    if not os.path.exists(input_path):
        print(f"Erro: Arquivo não encontrado: {input_path}", file=sys.stderr)
        return 1

    fmt = args.format.lower().lstrip(".")
    if fmt == "markdown":
        fmt = "md"

    doc_or_target = args.doc_lang if args.enhance_only and args.doc_lang else args.target_lang
    output_path = (
        os.path.abspath(args.output)
        if args.output
        else get_default_output_path(
            input_path,
            doc_or_target,
            fmt,
            bilingual=args.bilingual,
            enhance_only=args.enhance_only,
        )
    )

    opts = EnhancementOptions(
        normalize_chars=not args.no_normalize,
        reflow_sentences=not args.no_reflow,
        remove_headers_footers=not args.no_remove_headers,
        organize_toc=not args.no_organize_toc,
        force_heuristic_toc=args.force_discover_toc,
        footnote_mode=args.footnotes,
        include_back_to_toc=args.back_to_toc,
    )

    print(f"Arquivo de entrada: {input_path}")
    print(f"Modo: {'Apenas Aprimoramento / Conversão' if args.enhance_only else f'Tradução ({args.source_lang} -> {args.target_lang})'}")
    print(f"Formato escolhido: {fmt.upper()} -> {output_path}")

    last_pct = -1

    def _cli_status(done: int, total: int, status_msg: str, _preview: str) -> None:
        nonlocal last_pct
        pct = int((done / total) * 100) if total > 0 else 0
        if pct != last_pct or done == total or done == 0:
            last_pct = pct
            print(f"[{pct:3d}%] {status_msg}", flush=True)

    start_time = time.monotonic()
    try:
        if args.enhance_only:
            enhance_only_book_pipeline(
                input_path=input_path,
                output_path=output_path,
                output_format=fmt,
                doc_lang=doc_or_target,
                options=opts,
                start_page=args.start_page,
                end_page=args.end_page,
                status_callback=_cli_status,
            )
        else:
            translate_book_pipeline(
                input_path=input_path,
                output_path=output_path,
                output_format=fmt,
                source_lang=args.source_lang,
                target_lang=args.target_lang,
                bilingual=args.bilingual,
                options=opts,
                start_page=args.start_page,
                end_page=args.end_page,
                status_callback=_cli_status,
            )
        elapsed = time.monotonic() - start_time
        print(f"\nConcluído com sucesso em {elapsed:.1f}s!")
        print(f"Arquivo ({fmt.upper()}) salvo em: {output_path}")
        return 0
    except KeyboardInterrupt:
        print("\nOperação pausada pelo usuário. Todo o progresso foi salvo.")
        return 130
    except Exception as e:
        print(f"\nErro: {e}", file=sys.stderr)
        return 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tradutor e Aprimorador Completo de Livros (EPUB, PDF, HTML, Markdown, TXT)"
    )
    parser.add_argument("input", nargs="?", help="Caminho do livro de entrada (.pdf, .epub, .txt, .md).")
    parser.add_argument("-o", "--output", help="Caminho do arquivo de saída")
    parser.add_argument("-f", "--format", default="epub", choices=["epub", "pdf", "html", "md", "markdown", "txt"], help="Formato de saída")
    parser.add_argument("--enhance-only", action="store_true", help="Apenas aprimora e converte sem traduzir")
    parser.add_argument("-s", "--source-lang", default="auto", help="Idioma de origem (padrão: auto)")
    parser.add_argument("-t", "--target-lang", default="pt", help="Idioma de destino (padrão: pt)")
    parser.add_argument("--doc-lang", help="Idioma do livro no modo --enhance-only")
    parser.add_argument("-b", "--bilingual", action="store_true", help="Gera edição bilíngue")
    parser.add_argument("--no-normalize", action="store_true", help="Desativa normalização tipográfica")
    parser.add_argument("--no-reflow", action="store_true", help="Desativa reconstrução de frases")
    parser.add_argument("--no-remove-headers", action="store_true", help="Desativa remoção de cabeçalhos/rodapés")
    parser.add_argument("--no-organize-toc", action="store_true", help="Desativa descoberta automática de capítulos")
    parser.add_argument("--force-discover-toc", action="store_true", help="Força algoritmo visual/heurístico")
    parser.add_argument("--footnotes", default="move_end", choices=list(FOOTNOTE_MODES.keys()), help="Notas de rodapé")
    parser.add_argument("--back-to-toc", action="store_true", help="Adiciona link Voltar ao Sumário")
    parser.add_argument("--start-page", type=int, help="Página/capítulo inicial (base 1)")
    parser.add_argument("--end-page", type=int, help="Página/capítulo final (base 1)")
    parser.add_argument("--cli", action="store_true", help="Executa em linha de comando sem GUI")
    parser.add_argument("--gui", action="store_true", help="Abre a interface gráfica acessível")
    parser.add_argument("-V", "--version", action="store_true", help="Exibe a versão atual e encerra")
    parser.add_argument("--check-update", action="store_true", help="Verifica se há nova versão no GitHub Releases")
    parser.add_argument("--apply-update", action="store_true", help="Baixa e aplica a atualização disponível (apenas no .exe)")
    return parser


def _run_cli_update_check() -> int:
    result = check_for_updates()
    if result.error_message:
        print(f"Erro ao verificar atualizações: {result.error_message}", file=sys.stderr)
        return 1
    if result.update_available and result.manifest is not None:
        print(
            f"Nova versão disponível: v{result.manifest.version} (atual: v{result.current_version}). "
            "Use --apply-update ou o menu Ajuda (F5) para atualizar."
        )
        return 0
    print(f"Você já está na versão mais recente (v{result.current_version}).")
    return 0


def _run_cli_apply_update() -> int:
    result = check_for_updates()
    if result.error_message:
        print(f"Erro ao verificar atualizações: {result.error_message}", file=sys.stderr)
        return 1
    if not result.update_available or result.manifest is None:
        print(f"Você já está na versão mais recente (v{result.current_version}).")
        return 0
    last_pct = -1

    def _on_dl(downloaded: int, total: int) -> None:
        nonlocal last_pct
        pct = int((downloaded * 100) / total) if total > 0 else 0
        if pct != last_pct and (pct % 10 == 0 or pct == 100):
            last_pct = pct
            print(f"[{pct:3d}%] Baixando v{result.manifest.version}...", flush=True)

    try:
        staged = prepare_and_stage_update(result.manifest, progress_callback=_on_dl)
    except DevelopmentModeUpdateError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Falha ao baixar/preparar atualização: {exc}", file=sys.stderr)
        return 1
    trigger_update_and_exit_ready(staged, relaunch=False)
    print(f"Atualização v{result.manifest.version} preparada. Aplicando após encerrar...")
    return 0


def main() -> int:
    _attach_or_protect_stdio()
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.version:
        print(f"{APP_NAME} v{APP_VERSION}")
        return 0
    if args.check_update:
        return _run_cli_update_check()
    if args.apply_update:
        return _run_cli_apply_update()
    if args.cli and args.input:
        return run_cli(args)
    initial: Optional[str] = args.input if (args.input and os.path.exists(args.input)) else None
    return run_gui(initial_file=initial)


if __name__ == "__main__":
    sys.exit(main())
