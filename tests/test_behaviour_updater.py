# Role: policy
"""Testes 1-para-1 do Exemplo Concreto e dos Cenários 1 a 8 do atualizador interno."""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import wx

import book_translator
from src.adapters.github_release_client import download_release_archive, fetch_latest_manifest
from src.adapters.windows_swap_installer import build_trampoline_batch_content, stage_update_zip
from src.controllers.gui_frame import BookProcessorFrame
from src.controllers.gui_update_dialog import _handle_check_result
from src.domain.update_models import (
    DevelopmentModeUpdateError,
    IntegrityVerificationError,
    ReleaseManifest,
    StagedUpdate,
    UnsafeArchiveError,
    UpdateCheckResult,
    UpdateError,
)
from src.domain.version import APP_NAME, APP_VERSION
from src.policies.semver_policy import is_newer_version, parse_and_validate_manifest, parse_semver
from src.services.self_update_service import check_for_updates, prepare_and_stage_update
from tools.build_release_assets import build_release_assets

ROOT_DIR = Path(__file__).resolve().parent.parent


def _make_sample_zip_bytes(extra_entries: dict[str, bytes] | None = None) -> tuple[bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("TradutorLivros/TradutorLivros.exe", b"MZ_FAKE_EXE")
        zf.writestr("TradutorLivros/_internal/base.dll", b"DLL_CONTENT")
        if extra_entries:
            for name, payload in extra_entries.items():
                zf.writestr(name, payload)
    raw = buf.getvalue()
    return raw, hashlib.sha256(raw).hexdigest().lower()


class _StaticBytesHandler(http.server.BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, bytes]] = {}

    def do_GET(self) -> None:
        status, body = self.routes.get(self.path, (404, b"not found"))
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def _start_test_server(routes: dict[str, tuple[int, bytes]]) -> tuple[http.server.ThreadingHTTPServer, int]:
    class Handler(_StaticBytesHandler):
        pass

    Handler.routes = routes
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, port


class BehaviourUpdaterTests(unittest.TestCase):
    def test_00_concrete_usage_example_cli_and_manifest(self) -> None:
        out_ver = io.StringIO()
        with mock.patch.object(sys, "argv", ["book_translator.py", "--version"]), redirect_stdout(out_ver):
            rc = book_translator.main()
        self.assertEqual(rc, 0)
        self.assertEqual(out_ver.getvalue().strip(), f"{APP_NAME} v{APP_VERSION}")

        sample_manifest = {
            "version": "1.1.0",
            "tag": "v1.1.0",
            "published_at": "2026-11-13T18:00:00Z",
            "asset_name": "TradutorLivros-win64.zip",
            "download_url": "https://github.com/Thiago-Portella/tradutor-livros-acessivel/releases/download/v1.1.0/TradutorLivros-win64.zip",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "size_bytes": 48251904,
            "release_notes": "- Adicionado atualizador interno acessível via GitHub Releases\n- Melhorias de estabilidade",
        }
        parsed = parse_and_validate_manifest(json.dumps(sample_manifest))
        self.assertEqual(parsed.version, "1.1.0")
        self.assertEqual(parsed.tag, "v1.1.0")

        out_new = io.StringIO()
        new_res = UpdateCheckResult(current_version=APP_VERSION, update_available=True, manifest=parsed)
        with mock.patch("book_translator.check_for_updates", return_value=new_res):
            with mock.patch.object(sys, "argv", ["book_translator.py", "--check-update"]), redirect_stdout(out_new):
                self.assertEqual(book_translator.main(), 0)
        self.assertIn("Nova versão disponível: v1.1.0", out_new.getvalue())

        out_same = io.StringIO()
        same_res = UpdateCheckResult(current_version=APP_VERSION, update_available=False, manifest=parsed)
        with mock.patch("book_translator.check_for_updates", return_value=same_res):
            with mock.patch.object(sys, "argv", ["book_translator.py", "--check-update"]), redirect_stdout(out_same):
                self.assertEqual(book_translator.main(), 0)
        self.assertIn(f"Você já está na versão mais recente (v{APP_VERSION}).", out_same.getvalue())

        err_dev = io.StringIO()
        with mock.patch("book_translator.check_for_updates", return_value=new_res):
            with mock.patch.object(sys, "argv", ["book_translator.py", "--apply-update"]), redirect_stderr(err_dev):
                self.assertEqual(book_translator.main(), 1)
        self.assertIn("git pull", err_dev.getvalue())

        fake_staged = StagedUpdate(staging_dir="tmp", extracted_app_dir="tmp/app", manifest=parsed)
        out_apply = io.StringIO()
        with (
            mock.patch("book_translator.check_for_updates", return_value=new_res),
            mock.patch("book_translator.prepare_and_stage_update", return_value=fake_staged),
            mock.patch("book_translator.trigger_update_and_exit_ready", return_value="tmp/apply.cmd") as mock_trig,
            mock.patch.object(sys, "argv", ["book_translator.py", "--apply-update"]),
            redirect_stdout(out_apply),
        ):
            self.assertEqual(book_translator.main(), 0)
        mock_trig.assert_called_once_with(fake_staged, relaunch=False)
        self.assertIn("Aplicando após encerrar", out_apply.getvalue())

    def test_scenario_01_semver_comparison_deterministic(self) -> None:
        self.assertEqual(parse_semver("1.0.0"), (1, 0, 0))
        self.assertEqual(parse_semver("v1.2.3"), (1, 2, 3))
        self.assertTrue(is_newer_version("1.0.0", "1.1.0"))
        self.assertTrue(is_newer_version("1.0.2", "1.0.10"))
        self.assertFalse(is_newer_version("1.1.0", "1.1.0"))
        self.assertFalse(is_newer_version("1.2.0", "1.1.9"))
        with self.assertRaises(ValueError):
            parse_semver("1.2")

    def test_scenario_02_manifest_validation_strict(self) -> None:
        bad_http = json.dumps(
            {
                "version": "1.1.0",
                "tag": "v1.1.0",
                "asset_name": "TradutorLivros-win64.zip",
                "download_url": "http://insecure.example/a.zip",
                "sha256": "a" * 64,
            }
        )
        with self.assertRaises(UpdateError):
            parse_and_validate_manifest(bad_http)

        bad_sha = json.dumps(
            {
                "version": "1.1.0",
                "tag": "v1.1.0",
                "asset_name": "TradutorLivros-win64.zip",
                "download_url": "https://github.com/x/y/releases/download/v1.1.0/a.zip",
                "sha256": "curto",
            }
        )
        with self.assertRaises(UpdateError):
            parse_and_validate_manifest(bad_sha)

    def test_scenario_03_check_when_already_latest(self) -> None:
        manifest_eq = ReleaseManifest(
            version="1.1.0",
            tag="v1.1.0",
            published_at="",
            asset_name="TradutorLivros-win64.zip",
            download_url="https://github.com/x/y/releases/download/v1.1.0/a.zip",
            sha256="b" * 64,
            size_bytes=10,
            release_notes="",
        )
        res_eq = check_for_updates(current_version="1.1.0", fetch_fn=lambda _u: manifest_eq)
        self.assertFalse(res_eq.update_available)
        self.assertIsNone(res_eq.error_message)

        manifest_older = ReleaseManifest(
            version="1.0.9",
            tag="v1.0.9",
            published_at="",
            asset_name="TradutorLivros-win64.zip",
            download_url="https://github.com/x/y/releases/download/v1.0.9/a.zip",
            sha256="b" * 64,
            size_bytes=10,
            release_notes="",
        )
        res_older = check_for_updates(current_version="1.1.0", fetch_fn=lambda _u: manifest_older)
        self.assertFalse(res_older.update_available)
        self.assertIsNone(res_older.error_message)

    def test_scenario_04_silent_offline_check_resilient(self) -> None:
        valid_manifest = {
            "version": "1.2.0",
            "tag": "v1.2.0",
            "asset_name": "TradutorLivros-win64.zip",
            "download_url": "https://github.com/Thiago-Portella/tradutor-livros-acessivel/releases/download/v1.2.0/TradutorLivros-win64.zip",
            "sha256": "d" * 64,
            "size_bytes": 123,
            "release_notes": "Notas reais",
        }
        srv, port = _start_test_server({"/latest.json": (200, json.dumps(valid_manifest).encode("utf-8"))})
        try:
            fetched = fetch_latest_manifest(f"http://127.0.0.1:{port}/latest.json")
            self.assertEqual(fetched.version, "1.2.0")
            with self.assertRaises(UpdateError) as ctx_404:
                fetch_latest_manifest(f"http://127.0.0.1:{port}/missing.json")
            self.assertIn("Nenhuma publicação", str(ctx_404.exception))
        finally:
            srv.shutdown()
            srv.server_close()

        res = check_for_updates(current_version=APP_VERSION, manifest_url="http://127.0.0.1:1/unreachable.json")
        self.assertFalse(res.update_available)
        self.assertIsNone(res.manifest)
        self.assertIsNotNone(res.error_message)

        app = wx.App(False)
        frame = BookProcessorFrame(enable_startup_update_check=False)
        try:
            with mock.patch("src.controllers.gui_update_dialog.wx.MessageBox") as mock_box:
                _handle_check_result(frame, res, manual=False)
                mock_box.assert_not_called()
            menu_bar = frame.GetMenuBar()
            self.assertIsNotNone(menu_bar)
            self.assertEqual(menu_bar.GetMenuCount(), 1)
            self.assertIn("Ajuda", menu_bar.GetMenuLabelText(0))
        finally:
            frame.Destroy()
            wx.YieldIfNeeded()

    def test_scenario_05_streaming_download_and_sha256_verification(self) -> None:
        zip_bytes, good_sha = _make_sample_zip_bytes()
        srv, port = _start_test_server({"/good.zip": (200, zip_bytes), "/bad.zip": (200, b"CORRUPTED_ZIP")})
        try:
            manifest_ok = ReleaseManifest(
                version="1.1.0",
                tag="v1.1.0",
                published_at="",
                asset_name="TradutorLivros-win64.zip",
                download_url=f"http://127.0.0.1:{port}/good.zip",
                sha256=good_sha,
                size_bytes=len(zip_bytes),
                release_notes="ok",
            )
            progress_hits: list[tuple[int, int]] = []
            with tempfile.TemporaryDirectory() as tmp:
                dest_ok = os.path.join(tmp, "ok.zip")
                out = download_release_archive(
                    manifest_ok, dest_ok, progress_callback=lambda d, t: progress_hits.append((d, t))
                )
                self.assertEqual(out, dest_ok)
                self.assertTrue(os.path.exists(dest_ok))
                self.assertGreaterEqual(len(progress_hits), 1)

                manifest_bad = ReleaseManifest(
                    version="1.1.0",
                    tag="v1.1.0",
                    published_at="",
                    asset_name="TradutorLivros-win64.zip",
                    download_url=f"http://127.0.0.1:{port}/bad.zip",
                    sha256=good_sha,
                    size_bytes=13,
                    release_notes="bad",
                )
                dest_bad = os.path.join(tmp, "bad.zip")
                with self.assertRaises(IntegrityVerificationError):
                    download_release_archive(manifest_bad, dest_bad)
                self.assertFalse(os.path.exists(dest_bad))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_scenario_06_zip_slip_blocked_before_extraction(self) -> None:
        for evil_entry in ("../../evil.dll", "/evil_abs.dll", "C:\\Windows\\evil.dll"):
            evil_bytes, evil_sha = _make_sample_zip_bytes({evil_entry: b"BAD"})
            manifest = ReleaseManifest(
                version="1.1.0",
                tag="v1.1.0",
                published_at="",
                asset_name="TradutorLivros-win64.zip",
                download_url="https://github.com/x/y/releases/download/v1.1.0/a.zip",
                sha256=evil_sha,
                size_bytes=len(evil_bytes),
                release_notes="",
            )
            with tempfile.TemporaryDirectory() as tmp:
                evil_zip = os.path.join(tmp, "evil.zip")
                with open(evil_zip, "wb") as fh:
                    fh.write(evil_bytes)
                with self.assertRaises(UnsafeArchiveError):
                    stage_update_zip(evil_zip, os.path.join(tmp, "stage"), manifest)
                self.assertFalse(os.path.exists(os.path.join(tmp, "evil.dll")))

    def test_scenario_07_development_mode_protection(self) -> None:
        manifest = parse_and_validate_manifest(
            json.dumps(
                {
                    "version": "1.1.0",
                    "tag": "v1.1.0",
                    "asset_name": "TradutorLivros-win64.zip",
                    "download_url": "https://github.com/x/y/releases/download/v1.1.0/a.zip",
                    "sha256": "c" * 64,
                }
            )
        )
        with self.assertRaises(DevelopmentModeUpdateError) as ctx:
            prepare_and_stage_update(manifest, is_frozen=False)
        self.assertIn("git pull", str(ctx.exception))

    def test_scenario_08_release_assets_builder_and_trampoline_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dist_dir = Path(tmp) / "dist" / "TradutorLivros"
            (dist_dir / "_internal").mkdir(parents=True)
            (dist_dir / "TradutorLivros.exe").write_bytes(b"EXE_STUB")
            (dist_dir / "_internal" / "mod.pyd").write_bytes(b"PYD")
            out_dir = Path(tmp) / "release_assets"

            with self.assertRaises(ValueError):
                build_release_assets(tag="v9.9.9", repo="Thiago-Portella/tradutor-livros-acessivel", dist_dir=dist_dir, out_dir=out_dir)

            zip_path, manifest_path = build_release_assets(
                tag=f"v{APP_VERSION}",
                repo="Thiago-Portella/tradutor-livros-acessivel",
                dist_dir=dist_dir,
                out_dir=out_dir,
                release_notes="- Release inicial",
            )
            self.assertTrue(zip_path.is_file())
            self.assertTrue(manifest_path.is_file())
            validated = parse_and_validate_manifest(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(validated.version, APP_VERSION)

            cmd_relaunch = build_trampoline_batch_content(
                pid=12345,
                source_app_dir=r"C:\Temp\stage\TradutorLivros",
                target_app_dir=r"C:\Apps\TradutorLivros",
                relaunch=True,
            )
            root_copy_line = next(ln.strip() for ln in cmd_relaunch.splitlines() if ln.strip().startswith('robocopy "%SRC%" "%DST%"'))
            internal_copy_line = next(ln.strip() for ln in cmd_relaunch.splitlines() if ln.strip().startswith('robocopy "%SRC%\\_internal"'))
            self.assertNotIn("/PURGE", root_copy_line)
            self.assertNotIn("/MIR", root_copy_line)
            self.assertIn("/MIR", internal_copy_line)
            self.assertIn("PID eq 12345", cmd_relaunch)
            self.assertIn(r'start "" "C:\Apps\TradutorLivros\TradutorLivros.exe"', cmd_relaunch)
            self.assertIn('del "%~f0"', cmd_relaunch)

            cmd_no_relaunch = build_trampoline_batch_content(
                pid=12345,
                source_app_dir=r"C:\Temp\stage\TradutorLivros",
                target_app_dir=r"C:\Apps\TradutorLivros",
                relaunch=False,
            )
            self.assertNotIn('start ""', cmd_no_relaunch)


if __name__ == "__main__":
    unittest.main()
