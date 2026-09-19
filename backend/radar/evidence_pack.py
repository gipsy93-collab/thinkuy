"""Evidence Pack: carpeta de evidencia real del corpus para una pregunta.

Recuperación determinista (matching ponderado 3/2/1 + postura de controversia +
citas). Cada ítem lleva su fragmento literal (título/abstract) y DOI para que
cualquier síntesis — determinista o LLM — solo pueda citar evidencia existente.
"""
from __future__ import annotations

import sqlite3

from . import db
from . import topics as topics_mod
from .controversy import classify_stance
from .matching import parse_keywords, rank_articles


def build_pack(conn: sqlite3.Connection, topic: str, limit: int = 20,
               days: int = 3650) -> dict:
    kws = parse_keywords(topic)
    rows = conn.execute(
        "SELECT * FROM articles ORDER BY cited_by DESC, pub_date DESC LIMIT 2500"
    ).fetchall()
    arts = [db._row_to_article(r) for r in rows]
    ranked = [a for a in rank_articles(arts, kws) if a["match_score"] > 0][:limit]

    items = []
    journals = set()
    fields_count = {}
    for a in ranked:
        text = f"{a.get('abstract') or ''} {a.get('title') or ''}"
        stance = classify_stance(text)
        fields = topics_mod.classify_article_fields(a)
        fid = fields[0]["id"] if fields else "general"
        fields_count[fid] = fields_count.get(fid, 0) + 1
        if a.get("journal_title"):
            journals.add(a["journal_title"])
        items.append({
            "doi": a.get("doi"),
            "title": a.get("title"),
            "year": a.get("year"),
            "journal": a.get("journal_title"),
            "cited_by": a.get("cited_by"),
            "stance": stance,
            "match_score": a.get("match_score"),
            "matched": [m["keyword"] for m in (a.get("matched") or [])][:5],
            "thematic_field": fid,
            "fragment": (a.get("abstract") or "")[:500] or (a.get("title") or "")[:500],
        })

    return {
        "topic": topic,
        "query_keywords": kws,
        "n": len(items),
        "independent_journals": len(journals),
        "field_counts": fields_count,
        "items": items,
    }