#!/usr/bin/env python
"""Fuente única de la versión de los assets de la PWA.

El versionado estaba repartido en cuatro puntos que se desincronizaban solos
(medido: `index.html` pedía `app.js?v=5.45` mientras `sw.js` cacheaba `?v=5.44`,
lo que rompía el respaldo offline). Este script los mantiene alineados:

  - `pwa/index.html`  → `css/style.css?v=X` y `js/app.js?v=X`
  - `pwa/sw.js`       → `./css/style.css?v=X`, `./js/app.js?v=X` y `CACHE="thinkuy-vN"`

Uso:
  python tools/bump_pwa_version.py --check      # falla (exit 1) si hay desfase
  python tools/bump_pwa_version.py --bump       # sube el patch e invalida la caché
  python tools/bump_pwa_version.py --set 5.50   # fija una versión explícita
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "pwa" / "index.html"
SW = ROOT / "pwa" / "sw.js"

# (etiqueta, patrón en index.html, patrón en sw.js)
ASSETS = [
    ("css/style.css", re.compile(r"(css/style\.css\?v=)([\d.]+)"), re.compile(r"(\./css/style\.css\?v=)([\d.]+)")),
    ("js/app.js", re.compile(r"(js/app\.js\?v=)([\d.]+)"), re.compile(r"(\./js/app\.js\?v=)([\d.]+)")),
]
CACHE_RE = re.compile(r'(const CACHE = "thinkuy-v)(\d+)(")')


def _read() -> tuple[str, str]:
    return INDEX.read_text(encoding="utf-8"), SW.read_text(encoding="utf-8")


def current_versions() -> dict[str, str | None]:
    index, sw = _read()
    out: dict[str, str | None] = {}
    for label, idx_re, sw_re in ASSETS:
        m_idx = idx_re.search(index)
        m_sw = sw_re.search(sw)
        out[f"index::{label}"] = m_idx.group(2) if m_idx else None
        out[f"sw::{label}"] = m_sw.group(2) if m_sw else None
    m_cache = CACHE_RE.search(sw)
    out["cache"] = m_cache.group(2) if m_cache else None
    return out


def check() -> bool:
    versions = current_versions()
    asset_values = [v for k, v in versions.items() if k != "cache"]
    coherent = len(set(asset_values)) == 1 and None not in asset_values
    if coherent:
        print(f"OK  versión de assets coherente: {asset_values[0]}  (caché thinkuy-v{versions['cache']})")
    else:
        print("FALLO  versiones desalineadas:")
        for k, v in versions.items():
            print(f"  {k:20} = {v}")
    return coherent


def _write(asset_version: str, cache_version: str) -> None:
    index, sw = _read()
    for _label, idx_re, sw_re in ASSETS:
        index = idx_re.sub(rf"\g<1>{asset_version}", index)
        sw = sw_re.sub(rf"\g<1>{asset_version}", sw)
    sw = CACHE_RE.sub(rf"\g<1>{cache_version}\g<3>", sw)
    INDEX.write_text(index, encoding="utf-8")
    SW.write_text(sw, encoding="utf-8")


def _next_patch(version: str) -> str:
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sincroniza la versión de los assets de la PWA.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="verifica coherencia y sale con 1 si hay desfase")
    group.add_argument("--bump", action="store_true", help="sube el patch e invalida la caché")
    group.add_argument("--set", metavar="X.Y", help="fija una versión explícita")
    args = parser.parse_args()

    if args.check or not (args.bump or args.set):
        return 0 if check() else 1

    versions = current_versions()
    base = versions.get("index::js/app.js") or versions.get("index::css/style.css") or "0.0"
    cache = versions.get("cache") or "0"
    target = args.set or _next_patch(str(base))
    if not re.fullmatch(r"\d+\.\d+", target):
        print(f"Versión inválida: {target!r} (se espera X.Y)")
        return 2
    _write(target, str(int(cache) + 1))
    print(f"OK  assets -> {target} · cache -> thinkuy-v{int(cache) + 1}")
    return 0 if check() else 1


if __name__ == "__main__":
    sys.exit(main())
