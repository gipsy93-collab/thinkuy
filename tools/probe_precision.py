"""Sonda 2: línea base de precisión/recall del motor en vivo contra el oro del investigador.

Usa las decisiones de cribado de un protocolo real como juicio de relevancia:
- **Positivos** = artículos `included` (el investigador los consideró pertinentes).
- **Negativos** = muestra de `excluded` (los descartó en título/resumen).

Luego lanza la sonda en vivo con la pregunta del protocolo y mide cuántos positivos recupera
(recall@N) y qué proporción de los primeros N son positivos (precision@N). Es una **línea base**:
sin ella, añadir un re-ranker (p. ej. BGE-M3) sería fe.

Uso:
  python tools/probe_precision.py --db data/radar.db --protocol 15 --limit 100 \
      --out data/demo/probe_precision.json
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from radar.harvester import live_probe  # noqa: E402


def norm_doi(value) -> str:
    d = str(value or "").strip().lower()
    return d.replace("https://doi.org/", "").replace("http://doi.org/", "")


def load_gold(db_path: str, protocol_id: int, negatives: int = 200) -> dict:
    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    proto = conn.execute(
        "SELECT id,title,research_question FROM review_protocols WHERE id=?", (protocol_id,)
    ).fetchone()
    if not proto:
        conn.close()
        raise SystemExit(f"Protocolo {protocol_id} no encontrado")
    pos = [norm_doi(r["doi"]) for r in conn.execute(
        "SELECT doi FROM article_screenings WHERE protocol_id=? AND decision='included'", (protocol_id,)
    ) if norm_doi(r["doi"])]
    exc = [norm_doi(r["doi"]) for r in conn.execute(
        "SELECT doi FROM article_screenings WHERE protocol_id=? AND decision='excluded'", (protocol_id,)
    ) if norm_doi(r["doi"])]
    conn.close()
    random.seed(42)
    neg = random.sample(exc, min(negatives, len(exc))) if exc else []
    return {
        "title": proto["title"],
        "research_question": proto["research_question"],
        "positives": sorted(set(pos)),
        "negatives": sorted(set(neg)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Línea base de precisión/recall del motor en vivo.")
    ap.add_argument("--db", default="data/radar.db")
    ap.add_argument("--protocol", type=int, default=15)
    ap.add_argument("--query", default=None, help="Sobrescribe la pregunta del protocolo")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--out", default="data/demo/probe_precision.json")
    args = ap.parse_args()

    gold = load_gold(args.db, args.protocol)
    query = (args.query or gold["research_question"] or gold["title"] or "").strip()
    pos, neg = set(gold["positives"]), set(gold["negatives"])
    print(f"Protocolo {args.protocol}: {gold['title']}")
    print(f"Consulta: {query[:100]}")
    print(f"Oro: {len(pos)} positivos (incluidos), {len(neg)} negativos (excluidos muestreados)")

    res = live_probe.probe_topic(query=query, limit=args.limit)
    if not res:
        print("La sonda no devolvió nada.")
        return 1
    retrieved = [norm_doi(a.get("doi")) for a in (res.get("articles") or [])]
    retrieved = [d for d in retrieved if d]

    recuperados = sorted(pos & set(retrieved))
    falsos = sorted(neg & set(retrieved))
    recall = len(recuperados) / len(pos) if pos else 0.0

    precision_at = {}
    for n in (10, 20, 50, 100):
        top = retrieved[:n]
        if not top:
            precision_at[n] = None
            continue
        precision_at[n] = round(sum(1 for d in top if d in pos) / len(top), 3)

    salida = {
        "generado": datetime.now(timezone.utc).isoformat(),
        "protocol_id": args.protocol,
        "query": query,
        "consulta_usada": res.get("consulta_usada"),
        "relajada": res.get("relajada"),
        "recuperados_total": len(retrieved),
        "oro_positivos": len(pos),
        "oro_negativos": len(neg),
        "recall": round(recall, 3),
        "positivos_recuperados": recuperados,
        "negativos_recuperados": falsos,
        "precision_at": precision_at,
        "fuentes": (res.get("ecosystem") or {}).get("sources"),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nConsulta usada: {res.get('consulta_usada')}  (relajada={res.get('relajada')})")
    print(f"Recuperados: {len(retrieved)}  |  fuentes: {salida['fuentes']}")
    print(f"Recall (positivos recuperados): {len(recuperados)}/{len(pos)} = {recall:.1%}")
    print(f"Precision@N: {precision_at}")
    print(f"Negativos recuperados (falsos positivos): {len(falsos)}")
    print(f"Informe: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
