#!/usr/bin/env python
"""Humo de la PWA: carga la app en un navegador headless y falla si hay excepciones de JS.

Sirve como red de seguridad para la Fase 4 (refactor de la interfaz): verifica que la
aplicación arranca sin `pageerror` y que existen los contenedores clave.

Uso:
  python tools/smoke_pwa.py --start                 # arranca uvicorn, prueba y lo cierra
  python tools/smoke_pwa.py --url http://127.0.0.1:8000/app/   # contra un servidor ya activo
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK_IDS = ["view-home", "keywords", "btn-home-send"]
# Handlers invocados desde atributos `onclick` en HTML generado: deben existir en `window`.
CHECK_HANDLERS = [
    "launchSnowballFromDoi", "fetchArticleDetails", "fetchDeterministicAbstract",
    "onScreenDecision", "proponerPcc", "saveChartingRow",
]


def _wait_health(url: str, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def _run_page(url: str, timeout: int) -> int:
    from playwright.sync_api import sync_playwright

    page_errors: list[str] = []
    console_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.goto(url, wait_until="networkidle", timeout=timeout)
        missing = [i for i in CHECK_IDS if page.query_selector(f"#{i}") is None]
        missing_handlers = [h for h in CHECK_HANDLERS if page.evaluate(f"typeof window.{h}") != "function"]
        API_BASE = page.evaluate("window.__API_BASE")
        # Recorrer las vistas para forzar el render de cada una (detecta errores al pintar).
        for chip in page.query_selector_all("[data-view]"):
            try:
                chip.click()
                page.wait_for_timeout(250)
            except Exception:
                pass
        title = page.title()
        browser.close()

    print(f"titulo: {title!r}")
    print(f"ids faltantes: {missing}")
    print(f"handlers faltantes: {missing_handlers}")
    print(f"window.__API_BASE: {API_BASE!r}")
    if missing_handlers or API_BASE != "/api":
        page_errors.append("handlers o API base ausentes")
    if page_errors:
        print("pageerror (excepciones JS):")
        for e in page_errors:
            print("  -", e)
    if console_errors:
        print("console.error (avisos):")
        for e in console_errors[:20]:
            print("  -", e)

    ok = not page_errors and not missing
    print("SMOKE PWA:", "OK" if ok else "FALLO")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Humo de la PWA (Playwright headless).")
    parser.add_argument("--url", default="http://127.0.0.1:8123/app/")
    parser.add_argument("--start", action="store_true", help="arranca uvicorn y lo cierra al terminar")
    parser.add_argument("--timeout", type=int, default=20000)
    args = parser.parse_args()

    server = None
    tmp_data = tempfile.mkdtemp(prefix="thinkuy_smoke_")
    try:
        if args.start:
            env = dict(os.environ)
            env["THINKUY_DATA_DIR"] = tmp_data
            env["THINKUY_HOST"] = "127.0.0.1"
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "radar.api.main:app", "--host", "127.0.0.1", "--port", "8123"],
                cwd=str(ROOT / "backend"), env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if not _wait_health("http://127.0.0.1:8123"):
                print("FALLO: el servidor no respondio en /api/health")
                return 1
        return _run_page(args.url, args.timeout)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        import shutil
        shutil.rmtree(tmp_data, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
