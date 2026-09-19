"""CLI de cosecha: python -m radar.harvester.cli --sources scielo,crossref --days 365"""
from __future__ import annotations

import argparse
import logging
import sys

from .pipeline import run_pipeline

DEFAULT_COLLECTIONS = ["scl", "chl", "col", "mex", "arg", "esp", "prt", "cub", "per", "ury", "ven", "ecu"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="thinkuy-harvest", description="Thinkuy: cosecha de metadatos del campo")
    ap.add_argument("--sources", default="seed,scielo,latindex,latindex_articles,crossref,openalex,redalyc,enrich",
                    help="Fuentes separadas por coma: seed,scielo,latindex,latindex_articles,crossref,openalex,redalyc,core,europepmc,enrich")
    ap.add_argument("--days", type=int, default=365, help="Ventana temporal hacia atrás (días)")
    ap.add_argument("--max-articles", type=int, default=1500, help="Tope global de artículos por corrida")
    ap.add_argument("--collections", default=",".join(DEFAULT_COLLECTIONS),
                    help="Colecciones SciELO separadas por coma")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    report = run_pipeline(
        sources=[s.strip() for s in args.sources.split(",") if s.strip()],
        days=args.days,
        max_articles=args.max_articles,
        collections=[c.strip() for c in args.collections.split(",") if c.strip()],
    )
    print("\n" + "=" * 60)
    print("THINKUY — reporte de cosecha")
    print(f"Ventana: {report['date_from']} -> {report['date_to']}")
    for src, info in report["sources"].items():
        print(f"  {src:20s} {info}")
    print(f"  {'TOTAL':20s} revistas={report['journals']} artículos={report['articles']}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())