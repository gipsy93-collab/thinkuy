"""Calidad editorial de Thinkuy: SJR + cuartil por ISSN.

Compromiso de calidad del radar: priorizar revistas Q1/Q2 y solo cuando no hay
evidencia de alto calibre, descender a Q3/Q4 (nunca inventar cuartiles).

Fuente canónica: dataset Scimago Journal Rank (SJR) por ISSN, público y
descargable desde scimagojr.com (CSV) o vía API (clave gratuita). El dataset
local vive en `data/sjr/sjr.json` (ISSN → {sjr, quartile}) y se construye desde
el CSV oficial con `python -m radar.quality --build-index <scimagojr.csv>`.

Soberanía epistémica:
- Solo se marca Q1-Q4 cuando el SJR lo certifica; lo no cubierto queda `None`
  (tier "sin clasificar"), nunca se le inventa un cuartil.
- El cuartil ordena y filtra, pero el score temático determinista sigue mandando
  en el feed (relevance).
"""
from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path

from . import config, db

log = logging.getLogger("radar.quality")

QUARTILE_ORDER = {"Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3, None: 4}

# Bonus de prominencia que se suma al match_score SOLO para ordenar (nunca al score mostrado)
QUALITY_BONUS = {"Q1": 12, "Q2": 8, "Q3": 4, "Q4": 2, None: 0}

SJR_DIR = config.DATA_DIR / "sjr"
SJR_JSON = SJR_DIR / "sjr.json"
DEFAULT_CSV = SJR_DIR / "scimagojr.csv"

_index_cache: dict[str, dict] | None = None


# ---------------------------------------------------------------- índice SJR

def _norm_issn(value: str | None) -> str | None:
    v = (value or "").strip().upper()
    v = v.replace("ISSN ", "").replace(" ", "").replace("-", "")
    v = "".join(ch for ch in v if ch.isalnum())
    return v if (len(v) == 8 and v[:7].isdigit() and (v[7].isdigit() or v[7] == "X")) else None


def build_index(csv_path: Path) -> dict[str, dict]:
    """Convierte el CSV oficial de ScimagoJR en el índice por ISSN.

    Columnas esperadas del CSV (scimagojr): Sourceid, Title, Type, Issn,
    SJR, SJR Best Quartile, ... (el resto se ignora). Issn puede llevar varios
    separados por '; ' o ', ' y con prefijo 'ISSN '.
    """
    index: dict[str, dict] = {}
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            quartile = str(row.get("SJR Best Quartile") or "").strip().upper()
            if quartile not in ("Q1", "Q2", "Q3", "Q4"):
                continue
            try:
                sjr = float(row.get("SJR") or 0)
            except ValueError:
                sjr = 0.0
            issn_field = str(row.get("Issn") or "").replace("ISSN ", "")
            for raw in re.split(r"[;,]", issn_field):
                issn = _norm_issn(raw)
                if not issn:
                    continue
                index.setdefault(issn, {"sjr": sjr, "quartile": quartile})
    SJR_DIR.mkdir(parents=True, exist_ok=True)
    SJR_JSON.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    log.info("Índice SJR construido: %d ISSN de %s", len(index), csv_path)
    return index


def load_index(force: bool = False) -> dict[str, dict]:
    """Carga el índice SJR (cacheado en memoria)."""
    global _index_cache
    if _index_cache is None or force:
        _index_cache = {}
        if SJR_JSON.exists():
            try:
                _index_cache = json.loads(SJR_JSON.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                _index_cache = {}
    return _index_cache


def classify(issns: list[str]) -> dict | None:
    """Cuartil + SJR de una revista por cualquiera de sus ISSN.

    Devuelve {"quartile", "sjr"} o None si no está en el índice.
    """
    if not issns:
        return None
    idx = load_index()
    best: dict | None = None
    for raw in issns:
        issn = _norm_issn(raw)
        if not issn or issn not in idx:
            continue
        rec = idx[issn]
        if best is None or QUARTILE_ORDER[rec.get("quartile")] < QUARTILE_ORDER.get(best.get("quartile"), 4):
            best = rec
    return best


# ---------------------------------------------------------------- BD

def enrich_journals(conn) -> int:
    """Rellena sjr/quartile de las revistas desde el índice SJR (si existe)."""
    idx = load_index()
    if not idx:
        log.info("Sin índice SJR (%s): no se clasifican cuartiles.", SJR_JSON)
        return 0
    rows = conn.execute(
        "SELECT id, issn_print, issn_online FROM journals "
        "WHERE sjr IS NULL OR quartile IS NULL"
    ).fetchall()
    n = 0
    for r in rows:
        rec = classify([r["issn_print"], r["issn_online"]])
        if not rec:
            continue
        conn.execute(
            "UPDATE journals SET sjr = ?, quartile = ? WHERE id = ?",
            (rec["sjr"], rec["quartile"], r["id"]),
        )
        n += 1
    conn.commit()
    log.info("Calidad: %d revistas clasificadas por SJR", n)
    return n


def journal_tier(conn, issn: str | None, title: str | None = None) -> tuple[str | None, float | None]:
    """Cuartil y SJR de una revista por ISSN (o título)."""
    rec = classify([issn] if issn else [])
    if rec:
        return rec["quartile"], rec.get("sjr")
    if title:
        t = " ".join(str(title).lower().split())
        row = conn.execute(
            "SELECT sjr, quartile FROM journals WHERE lower(title) = ? LIMIT 1",
            (t,),
        ).fetchone()
        if row and row["quartile"]:
            return row["quartile"], row["sjr"]
    return None, None


def build_tier_map(conn) -> tuple[dict, dict]:
    """Mapas issn_norm→tier y título_lower→tier para anotar artículos en lote."""
    qmap_issn: dict[str, str] = {}
    qmap_title: dict[str, str] = {}
    rows = conn.execute(
        "SELECT issn_print, issn_online, title, quartile FROM journals WHERE quartile IS NOT NULL"
    ).fetchall()
    for r in rows:
        q = r["quartile"]
        for i in (r["issn_print"], r["issn_online"]):
            n = _norm_issn(i)
            if n:
                qmap_issn.setdefault(n, q)
        t = (r["title"] or "").strip().lower()
        if t:
            qmap_title.setdefault(t, q)
    return qmap_issn, qmap_title


def tier_of_article(a: dict, qmap_issn: dict, qmap_title: dict) -> str | None:
    """Tier de un artículo a partir de los mapas del catálogo."""
    issn = _norm_issn(a.get("issn"))
    if issn and issn in qmap_issn:
        return qmap_issn[issn]
    t = (a.get("journal_title") or "").strip().lower()
    if t and t in qmap_title:
        return qmap_title[t]
    # Último recurso: el índice directo (p. ej. artículo cuyo ISSN no está en journals)
    rec = classify([a.get("issn")] if a.get("issn") else [])
    return rec["quartile"] if rec else None


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        prog="thinkuy-quality",
        description="Calidad editorial: índice SJR (Scimago) para revistas de Thinkuy")
    ap.add_argument("--build-index", metavar="CSV", default=None,
                    help="Construir data/sjr/sjr.json desde el CSV oficial de ScimagoJR")
    ap.add_argument("--enrich", action="store_true",
                    help="Rellenar sjr/quartile de las revistas en la BD")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.build_index:
        idx = build_index(Path(args.build_index))
        print(f"Índice SJR: {len(idx)} ISSN indexados -> {SJR_JSON}")

    if args.enrich or (args.build_index is None and not args.enrich):
        conn = db.connect()
        try:
            db.init_db(conn)
            n = enrich_journals(conn)
            print(f"Revistas clasificadas: {n}")
            st = conn.execute(
                "SELECT quartile, COUNT(*) n FROM journals WHERE quartile IS NOT NULL GROUP BY quartile"
            ).fetchall()
            for r in st:
                print(f"  {r['quartile']}: {r['n']}")
            total = conn.execute("SELECT COUNT(*) n FROM journals").fetchone()["n"]
            print(f"  sin clasificar: {total - sum(r['n'] for r in st)}")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())