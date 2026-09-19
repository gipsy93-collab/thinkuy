"""
build_cc_inlinks.py — In-links REALES por dominio desde el WebGraph de Common Crawl.

Calcula, para un conjunto de dominios objetivo (revistas del catálogo), qué dominios
les enlazan (referring domains) y cuántos enlaces aportan, recorriendo UNA vez el grafo
real de Common Crawl (vertices ⟨id, rev domain, num hosts⟩ + edges ⟨from_id, to_id⟩).

Salida: CC_INLINKS_DB (def: D:\\cc_inlinks.db), tabla cc_inlinks:
  target_domain_norm, referrer_domain_norm, count, release_id

SCIVIS (get_real_referrers) consume esta base para la columna IN-LINKS de la auditoría.

Uso:
  python tools/build_cc_inlinks.py \
      --vertices D:\\cc_main-2026-jun-jul-aug-domain-vertices.txt.gz \
      --edges D:\\cc_edges.txt.gz \
      --targets dominios.txt \
      --release cc-main-2026-jun-jul-aug

Requisitos: vertices y edges deben pertenecer al MISMO release (de data.commoncrawl.org).
Nota: recorrer las aristas (varios GB) es un proceso por lotes; ejecútalo fuera de hora.
"""
from __future__ import annotations

import argparse
import gzip
import os
import sqlite3
import sys
import time

DEFAULT_OUT = os.environ.get("THINKUY_CC_INLINKS_DB", r"D:\cc_inlinks.db")
RELEASE = os.environ.get("THINKUY_CC_RELEASE", "cc-main-2026-jun-jul-aug")


def _norm_domain_rev(rev: str) -> str:
    """Convierte 'com.example.sub' (rev) en 'sub.example.com' normalizado."""
    return ".".join(reversed(rev.strip().split("."))).lower()


def _load_targets(path: str) -> set[str]:
    out = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            d = line.strip().lower()
            if not d or d == "n/d":
                continue
            d = d.replace("https://", "").replace("http://", "").split("/")[0]
            while d.startswith("www."):
                d = d[4:]
            if d:
                out.add(d)
    return out


def _iter_vertices(gz_path: str):
    with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.strip().split("\t")
            if len(parts) < 2:
                continue
            try:
                vid = int(parts[0])
            except ValueError:
                continue
            rev_domain = parts[1]
            if "." not in rev_domain:
                continue
            yield vid, rev_domain


def _iter_edges(gz_path: str):
    with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.strip().split("\t")
            if len(parts) < 2:
                continue
            try:
                yield int(parts[0]), int(parts[1])
            except ValueError:
                continue


def build(vertices_gz: str, edges_gz: str, targets_path: str, out_db: str, release: str) -> None:
    print("Cargando dominios objetivo...")
    targets = _load_targets(targets_path)
    print(f"  {len(targets)} dominios objetivo")

    # Pase A: id -> domain para los objetivos
    target_ids: dict[int, str] = {}
    t0 = time.time()
    for vid, rev in _iter_vertices(vertices_gz):
        dom = _norm_domain_rev(rev)
        if dom in targets:
            target_ids[vid] = dom
    print(f"Pase A (vertices → ids objetivo): {len(target_ids)} ids en {time.time()-t0:.1f}s")

    # Pase B: recorrer aristas y contar in-links hacia objetivos
    in_counts: dict[int, dict[str, int]] = {}  # target_id -> {referrer_id: count}
    t0 = time.time()
    n_edges = 0
    for frm, to in _iter_edges(edges_gz):
        n_edges += 1
        if to in target_ids:
            in_counts.setdefault(to, {}).setdefault(frm, 0)
            in_counts[to][frm] += 1
    print(f"Pase B (edges): {n_edges:,} aristas en {time.time()-t0:.1f}s")

    # Pase C: resolver ids de referrers a dominios
    referrer_ids = {frm for bucket in in_counts.values() for frm in bucket}
    id_to_domain: dict[int, str] = {}
    t0 = time.time()
    for vid, rev in _iter_vertices(vertices_gz):
        if vid in referrer_ids:
            id_to_domain[vid] = _norm_domain_rev(rev)
            if len(id_to_domain) == len(referrer_ids):
                break
    print(f"Pase C (referrers → dominios): {len(id_to_domain)} resueltos en {time.time()-t0:.1f}s")

    # Escritura
    if os.path.exists(out_db):
        os.remove(out_db)
    conn = sqlite3.connect(out_db)
    conn.execute("""CREATE TABLE cc_inlinks (
        target_domain_norm TEXT, referrer_domain_norm TEXT, count INTEGER, release_id TEXT
    )""")
    rows = []
    for tid, bucket in in_counts.items():
        tdom = target_ids[tid]
        for rid, cnt in sorted(bucket.items(), key=lambda x: -x[1]):
            rdom = id_to_domain.get(rid)
            if not rdom or rdom == tdom:
                continue
            rows.append((tdom, rdom, cnt, release))
    conn.executemany("INSERT INTO cc_inlinks VALUES (?,?,?,?)", rows)
    conn.execute("CREATE INDEX idx_inlinks_target ON cc_inlinks(target_domain_norm)")
    conn.commit()
    conn.close()
    print(f"Base de in-links lista: {out_db} ({len(rows):,} pares objetivo/referrer)")


def main() -> int:
    ap = argparse.ArgumentParser(description="In-links reales por dominio desde el WebGraph de Common Crawl")
    ap.add_argument("--vertices", required=True, help="Archivo domain-vertices.txt.gz del release")
    ap.add_argument("--edges", required=True, help="Archivo domain-edges.txt.gz del mismo release")
    ap.add_argument("--targets", required=True, help="Archivo de dominios objetivo (uno por línea)")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"Base de salida (def: {DEFAULT_OUT})")
    ap.add_argument("--release", default=RELEASE, help=f"Release del grafo (def: {RELEASE})")
    args = ap.parse_args()

    for p in (args.vertices, args.edges, args.targets):
        if not os.path.exists(p):
            print(f"Falta archivo: {p}")
            return 1

    build(args.vertices, args.edges, args.targets, args.out, args.release)
    return 0


if __name__ == "__main__":
    sys.exit(main())