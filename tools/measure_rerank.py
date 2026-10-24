"""Mide el efecto del re-ranker BGE-M3 contra la línea base del motor en vivo.

Usa el oro del investigador (decisiones `included` de un protocolo) y compara precision@k y
recall **antes y después** de reordenar. Sin esta medición, activar el re-ranker sería fe.

Requiere un entorno con `sentence-transformers` (p. ej. el de Unsloth), no el del servidor:

  python tools/measure_rerank.py --db data/radar.db --protocol 15 \
      --query "marcos normativos ciencia ciudadana" --limit 100 \
      --out data/demo/rerank_measure.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from probe_precision import load_gold, norm_doi  # noqa: E402
from radar import rerank as rr  # noqa: E402
from radar.harvester import live_probe  # noqa: E402

KS = (10, 20, 50, 100)


def precision_at(orden: list[str], positivos: set[str]) -> dict:
    salida = {}
    for k in KS:
        top = orden[:k]
        salida[k] = round(sum(1 for d in top if d in positivos) / len(top), 3) if top else None
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description="Mide el re-ranker BGE-M3 contra la línea base.")
    ap.add_argument("--db", default="data/radar.db")
    ap.add_argument("--protocol", type=int, default=15)
    ap.add_argument("--query", default="marcos normativos ciencia ciudadana")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--out", default="data/demo/rerank_measure.json")
    ap.add_argument("--candidates", default=None,
                    help="Caché de candidatos (por defecto <out>.candidates.json). Reutiliza la "
                         "misma lista para que el antes/después no dependa de la red.")
    ap.add_argument("--refresh", action="store_true", help="Ignora la caché y vuelve a sondear")
    args = ap.parse_args()

    gold = load_gold(args.db, args.protocol)
    pos = set(gold["positives"])
    print(f"Oro: {len(pos)} positivos · consulta: {args.query}")

    out = Path(args.out)
    cand_path = Path(args.candidates) if args.candidates else out.with_suffix(".candidates.json")
    if cand_path.exists() and not args.refresh:
        datos = json.loads(cand_path.read_text(encoding="utf-8"))
        arts = datos.get("articles") or []
        consulta_usada = datos.get("consulta_usada")
        print(f"Candidatos (caché): {len(arts)}")
    else:
        res = live_probe.probe_topic(query=args.query, limit=args.limit)
        arts = res.get("articles") or []
        consulta_usada = res.get("consulta_usada")
        cand_path.parent.mkdir(parents=True, exist_ok=True)
        cand_path.write_text(json.dumps({"consulta_usada": consulta_usada, "articles": arts},
                                        ensure_ascii=False), encoding="utf-8")
        print(f"Candidatos (sonda): {len(arts)} · consulta usada: {consulta_usada}")

    antes = [norm_doi(a.get("doi")) for a in arts]
    antes = [d for d in antes if d]

    print("Cargando BGE-M3 y reordenando (la primera vez descarga el modelo)...")
    ordenados, info = rr.rerank(arts, args.query)
    if not info.get("aplicado"):
        print(f"Re-ranker NO aplicado: {info.get('motivo')}")
        return 1
    despues = [norm_doi(a.get("doi")) for a in ordenados]
    despues = [d for d in despues if d]

    vecindarios = rr.sugerir_vecindarios(ordenados)

    salida = {
        "generado": datetime.now(timezone.utc).isoformat(),
        "protocol_id": args.protocol,
        "query": args.query,
        "consulta_usada": consulta_usada,
        "modelo": info.get("modelo"),
        "candidatos": len(arts),
        "oro_positivos": len(pos),
        "antes": {"precision_at": precision_at(antes, pos),
                  "recall": round(len(pos & set(antes)) / len(pos), 3) if pos else 0.0},
        "despues": {"precision_at": precision_at(despues, pos),
                    "recall": round(len(pos & set(despues)) / len(pos), 3) if pos else 0.0},
        "vecindarios_sugeridos": len(vecindarios),
        "top10_despues": [{"doi": a.get("doi"), "title": (a.get("title") or "")[:80],
                           "score": a.get("_rerank_score"),
                           "en_oro": norm_doi(a.get("doi")) in pos} for a in ordenados[:10]],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n-- precision@k --")
    print(f"antes:   {salida['antes']['precision_at']}")
    print(f"despues: {salida['despues']['precision_at']}")
    print(f"recall antes/despues: {salida['antes']['recall']} / {salida['despues']['recall']}")
    print(f"vecindarios sugeridos: {salida['vecindarios_sugeridos']}")
    print(f"Informe: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
