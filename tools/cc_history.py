"""
cc_history.py — Multi-release del WebGraph de Common Crawl (serie histórica REAL).

Descarga e indexa los `domain-ranks.txt.gz` de varios releases oficiales de Common Crawl
en CC_HISTORY_DIR (def: D:\\cc_ranks_history), uno por release (cc_ranks_<release>.db),
cada uno con su metadata (release_id, etiqueta, orden cronológico, total de dominios).

SCIVIS (radar/scivis.py) consulta esta carpeta para construir la trayectoria histórica
de Centralidad Armónica y PageRank con datos 100% reales (nunca interpolados).

Uso:
  python tools/cc_history.py --status
  python tools/cc_history.py --release cc-main-2026-mar-apr-may
  python tools/cc_history.py --all            # descarga+indexa todos los del registro
  python tools/cc_history.py --registry mi_registro.txt   # registro personalizado

Formato de registro personalizado (TSV, sin cabecera):
  release_id<TAB>period_label<TAB>period_sort

La URL se construye como https://data.commoncrawl.org/projects/hyperlinkgraph/<id>/domain/<id>-domain-ranks.txt.gz
(si algún release del registro devuelve 404, se avisa y se omite, para no fabricar datos).
"""
from __future__ import annotations

import argparse
import importlib
import os
import sqlite3
import sys
import time
import urllib.request

HISTORY_DIR = os.environ.get("THINKUY_CC_HISTORY_DIR", r"D:\cc_ranks_history")
USER_AGENT = "Thinkuy-Scivis-History/1.0"

# Registro de releases confirmados (publicados en commoncrawl.org/blog). Extensible vía --registry.
DEFAULT_REGISTRY = [
    ("cc-main-2026-jan-feb-mar", "2026 Ene-Mar", 202601),
    ("cc-main-2026-feb-mar-apr", "2026 Feb-Abr", 202602),
    ("cc-main-2026-mar-apr-may", "2026 Mar-May", 202603),
    ("cc-main-2026-apr-may-jun", "2026 Abr-Jun", 202604),
    ("cc-main-2026-may-jun-jul", "2026 May-Jul", 202605),
    ("cc-main-2026-jun-jul-aug", "2026 Jun-Ago", 202606),
]


def _load_registry(path: str | None) -> list[tuple[str, str, int]]:
    if not path:
        return DEFAULT_REGISTRY
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.strip().split("\t")
            if len(parts) >= 3 and parts[0]:
                out.append((parts[0], parts[1], int(parts[2])))
    return out


def ranks_url(release_id: str) -> str:
    return (f"https://data.commoncrawl.org/projects/hyperlinkgraph/"
            f"{release_id}/domain/{release_id}-domain-ranks.txt.gz")


def download(url: str, out_path: str) -> bool:
    """Descarga con reanudación. Devuelve True si el archivo quedó completo."""
    existing = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    headers = {"User-Agent": USER_AGENT}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp, open(out_path, "ab" if existing else "wb") as out:
            if existing and resp.status == 200:
                # servidor ignora Range → reiniciar
                out.seek(0)
                out.truncate()
                existing = 0
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        return True
    except urllib.error.HTTPError as e:
        print(f"  [HTTP {e.code}] {url} (release inexistente o no publicado) — omitido.")
        return False
    except Exception as e:
        print(f"  [Error] descarga de {url}: {e} (se reintentará en otra corrida).")
        return False


def index_release(input_gz: str, output_db: str, release_id: str, label: str, sort: int) -> None:
    os.environ["THINKUY_CC_RANKS_GZ"] = input_gz
    os.environ["THINKUY_CC_RANKS_DB"] = output_db
    os.environ["THINKUY_CC_RELEASE"] = release_id
    os.environ["THINKUY_CC_PERIOD_LABEL"] = label
    os.environ["THINKUY_CC_PERIOD_SORT"] = str(sort)
    try:
        import index_cc_ranks as idx
    except ImportError:
        import tools.index_cc_ranks as idx
    importlib.reload(idx)
    idx.index_ranks()


def ensure_release(release_id: str, label: str, sort: int, force: bool = False) -> None:
    db_path = os.path.join(HISTORY_DIR, f"cc_ranks_{release_id}.db")
    if os.path.exists(db_path) and not force:
        print(f"[skip] {release_id} ya indexado: {db_path}")
        return
    os.makedirs(HISTORY_DIR, exist_ok=True)
    gz_path = os.path.join(HISTORY_DIR, f"{release_id}-domain-ranks.txt.gz")
    print(f"[descarga] {release_id} ({label})")
    ok = download(ranks_url(release_id), gz_path)
    if not ok:
        return
    print(f"[index] {release_id}")
    index_release(gz_path, db_path, release_id, label, sort)


def status() -> None:
    if not os.path.isdir(HISTORY_DIR):
        print(f"No existe {HISTORY_DIR}. Ejecuta --all o --release para poblarlo.")
        return
    print(f"Releases históricos indexados en {HISTORY_DIR}:")
    for fname in sorted(os.listdir(HISTORY_DIR)):
        if not fname.endswith(".db"):
            continue
        db = os.path.join(HISTORY_DIR, fname)
        try:
            conn = sqlite3.connect(db)
            row = conn.execute(
                "SELECT release_id, period_label, total_domains FROM cc_index_meta LIMIT 1"
            ).fetchone()
            conn.close()
            if row:
                print(f"  {row[0]:30s} {row[1]:14s} {row[2]:>10,} dominios")
            else:
                print(f"  {fname} (sin metadata)")
        except Exception:
            print(f"  {fname} (no legible)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Serie histórica real del WebGraph de Common Crawl")
    ap.add_argument("--status", action="store_true", help="Listar releases ya indexados")
    ap.add_argument("--all", action="store_true", help="Descargar e indexar todo el registro")
    ap.add_argument("--release", metavar="ID", default=None, help="Release específico del registro")
    ap.add_argument("--registry", metavar="PATH", default=None, help="Registro personalizado TSV")
    ap.add_argument("--force", action="store_true", help="Re-indexar aunque exista")
    args = ap.parse_args()

    registry = _load_registry(args.registry)

    if args.status:
        status()
        return 0

    targets = []
    if args.all:
        targets = registry
    elif args.release:
        match = [r for r in registry if r[0] == args.release]
        if not match:
            print(f"Release '{args.release}' no está en el registro. Usa --registry con un archivo TSV propio.")
            return 1
        targets = match
    else:
        ap.print_help()
        return 1

    for rid, label, sort in targets:
        ensure_release(rid, label, sort, force=args.force)
    status()
    return 0


if __name__ == "__main__":
    sys.exit(main())