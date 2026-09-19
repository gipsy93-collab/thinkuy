"""
web_twins_build.py — Caché local de vecinos del host-embedding de Common Crawl.

Consulta el Space público https://huggingface.co/spaces/commoncrawl/web-graph-knn
(128-d, release cc-main-2025-26-nov-dec-jan) para un lote de hosts y guarda los
top-K vecinos en SQLite (data/web_twins.db) para que la auditoría SCIVIS los sirva
sin depender de la red:
    hosts(host, neighbor_host, neighbor_domain, cosine, k_rank, release, created_at)

Requisito: pip install gradio_client (solo para esta herramienta, no para el server).

Uso:
  python tools/web_twins_build.py            # hosts de scivis_store + scratch/dominios.txt
  python tools/web_twins_build.py --hosts a.com b.com
  python tools/web_twins_build.py --k 20
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.parse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from radar import config  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "web_twins.db"
RELEASE = "cc-main-2025-26-nov-dec-jan"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS hosts (
               host TEXT, neighbor_host TEXT, neighbor_domain TEXT,
               cosine REAL, k_rank INTEGER, release TEXT, created_at REAL,
               PRIMARY KEY (host, k_rank)
           )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_wt_host ON hosts(host)")
    conn.commit()


def collect_hosts(extra: list[str]) -> list[str]:
    hosts: list[str] = []
    seen = set()

    def add(h: str) -> None:
        h = (h or "").strip().lower()
        h = h.replace("https://", "").replace("http://", "").split("/")[0]
        while h.startswith("www."):
            h = h[4:]
        if h and "." in h and h not in seen:
            seen.add(h)
            hosts.append(h)

    for h in extra:
        add(h)
    store = PROJECT_ROOT / "data" / "scivis_store.db"
    if store.exists():
        c = sqlite3.connect(store)
        for (d,) in c.execute("SELECT DISTINCT domain FROM audits WHERE domain NOT IN ('', 'N/D')"):
            add(d)
        c.close()
    domfile = PROJECT_ROOT / "scratch" / "dominios.txt"
    if domfile.exists():
        for line in domfile.read_text(encoding="utf-8").splitlines():
            add(line)
    return hosts


def query_space(client, host: str, k: int, retries: int = 3) -> list[tuple]:
    last_err = None
    for attempt in range(retries):
        try:
            out = client.predict(host, k, api_name="/search")
            info, df = out[0], out[1]
            if not df or not df.get("data"):
                return []
            rows = []
            for r in df["data"]:
                # r: ['#', 'host', cosine, 'registrable domain', 'same site', 'open']
                try:
                    rows.append((str(r[1]), str(r[3] or ""), float(r[2]), int(r[0])))
                except Exception:
                    continue
            return rows
        except Exception as e:
            last_err = e
            time.sleep(4 + attempt * 4)
    print(f"  ! fallo consultando {host}: {last_err}", flush=True)
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hosts", nargs="*", default=[])
    ap.add_argument("--only", action="store_true", help="procesar SOLO los --hosts dados (sin lote de dominios.txt/scivis_store)")
    ap.add_argument("--k", type=int, default=15)
    ap.add_argument("--force", action="store_true", help="recalcular aunque ya exista en caché")
    args = ap.parse_args()

    try:
        from gradio_client import Client
    except ImportError:
        print("Falta gradio_client:  pip install gradio_client")
        return 1

    hosts = [h.strip().lower() for h in args.hosts if h.strip()] if args.only else collect_hosts(args.hosts)
    conn = sqlite3.connect(DB_PATH)
    ensure_schema(conn)

    todo = []
    for h in hosts:
        has = conn.execute("SELECT COUNT(*) FROM hosts WHERE host = ?", (h,)).fetchone()[0]
        if not has or args.force:
            todo.append(h)
    print(f"{len(hosts)} hosts candidatos, {len(todo)} por calcular", flush=True)
    if not todo:
        return 0

    space = Client("commoncrawl/web-graph-knn", verbose=False)
    t0 = time.time()
    done = 0
    for h in todo:
        conn.execute("DELETE FROM hosts WHERE host = ?", (h,))
        rows = query_space(space, h, args.k)
        now = time.time()
        for nh, nd, cos, rank in rows:
            conn.execute(
                "INSERT OR REPLACE INTO hosts VALUES (?,?,?,?,?,?,?)",
                (h, nh, nd, cos, rank, RELEASE, now),
            )
        conn.commit()
        done += 1
        print(f"[{done}/{len(todo)}] {h} -> {len(rows)} vecinos  ({(time.time()-t0)/60:.1f} min)", flush=True)
        time.sleep(1.2)
    conn.close()
    print(f"Listo. Caché en {DB_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
