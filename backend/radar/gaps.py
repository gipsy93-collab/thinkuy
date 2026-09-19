"""Detección de vacíos de evidencia + «tres preguntas focales» (determinista).

Tipos de vacío:
1. Pares sub-explorados: keywords frecuentes por separado que casi nunca co-ocurren.
2. Corpus denso sin síntesis: temas con muchos papers pero pocas revisiones/síntesis.
3. Keywords emergentes: términos cuya primera aparición en catálogo es reciente.
4. Fuentes infra-citadas: obras con muchas referencias pero pocas citas recibidas.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

from .normalize import norm

_SYNTHESIS_TERMS = ("revisión", "revision", "scoping", "síntesis", "sintesis",
                    "sistemática", "sistematica", "review", "meta-análisis", "meta-análise")


def _article_keyword_sets(conn: sqlite3.Connection):
    """Devuelve (inverted_index kw→ids, freq) sobre las keywords de los artículos."""
    inverted: dict[str, set[int]] = {}
    rows = conn.execute("SELECT id, keywords FROM articles").fetchall()
    for r in rows:
        try:
            kws = json.loads(r["keywords"] or "[]")
        except json.JSONDecodeError:
            continue
        for kw in kws:
            k = norm(kw.get("k") if isinstance(kw, dict) else kw)
            if len(k) >= 3:
                inverted.setdefault(k, set()).add(r["id"])
    freq = {k: len(v) for k, v in inverted.items()}
    return inverted, freq


def keyword_frequency(conn: sqlite3.Connection, min_n: int = 2, top: int = 200) -> list[dict]:
    """Keywords más frecuentes del catálogo (índice invertido)."""
    _inv, freq = _article_keyword_sets(conn)
    return [{"kw": k, "n": n} for k, n in sorted(freq.items(), key=lambda kv: -kv[1])
            if n >= min_n][:top]


def under_explored_pairs(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Pares de keywords frecuentes (por separado) con baja co-ocurrencia real."""
    inv, freq = _article_keyword_sets(conn)
    top_kws = [k for k, _ in sorted(freq.items(), key=lambda kv: -kv[1]) if freq[k] >= 4][:60]
    pairs: list[tuple[int, str, str, int]] = []
    for i in range(len(top_kws)):
        for j in range(i + 1, len(top_kws)):
            a, b = top_kws[i], top_kws[j]
            co = len(inv[a] & inv[b])
            expected = min(freq[a], freq[b])
            if co < max(1, expected // 4):
                pairs.append((expected, a, b, co))
    pairs.sort(reverse=True)
    return [{"keyword_a": a, "keyword_b": b, "expected_intersection": expected, "actual_cooccurrence": co}
            for expected, a, b, co in pairs[:limit]]


def _article_blobs(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """Blobs normalizados (título+abstract+keywords) de todos los artículos."""
    rows = conn.execute("SELECT id, title, abstract, keywords FROM articles").fetchall()
    out = []
    for r in rows:
        try:
            kws = json.loads(r["keywords"] or "[]")
        except json.JSONDecodeError:
            kws = []
        blob = " ".join(filter(None, [r["title"], r["abstract"], " ".join(
            str(k.get("k") if isinstance(k, dict) else k) for k in kws)]))
        out.append((r["id"], norm(blob)))
    return out


def dense_without_synthesis(conn: sqlite3.Connection, limit: int = 8) -> list[dict]:
    """Temas (campos del perfil) con corpus denso pero poca síntesis."""
    from . import profile
    blobs = _article_blobs(conn)
    topics = profile.field_profile.topics
    out = []
    for f in topics:
        kws = [norm(k) for k in f["keywords_es"][:4]]
        n = 0
        for _aid, blob in blobs:
            if all(k in blob for k in kws):
                n += 1
        synth_n = sum(1 for _aid, blob in blobs if any(t in blob for t in _SYNTHESIS_TERMS))
        if n >= 3 and synth_n < max(1, n // 4):
            out.append({"field": f["name"], "id": f["id"], "articles": n,
                        "synthesis": synth_n, "gap": n - synth_n})
    out.sort(key=lambda x: -x["gap"])
    return out[:limit]


def emerging_keywords(conn: sqlite3.Connection, days: int = 365, limit: int = 8) -> list[dict]:
    """Keywords cuya primera aparición en catálogo es reciente (tendencia emergente)."""
    rows = conn.execute("SELECT keywords, year FROM articles WHERE year IS NOT NULL ORDER BY year").fetchall()
    first_year: dict[str, int] = {}
    count: dict[str, int] = {}
    for r in rows:
        try:
            kws = json.loads(r["keywords"] or "[]")
        except json.JSONDecodeError:
            continue
        for kw in kws:
            k = norm(kw.get("k") if isinstance(kw, dict) else kw)
            if len(k) < 4:
                continue
            count[k] = count.get(k, 0) + 1
            first_year[k] = min(first_year.get(k, 9999), r["year"] or 9999)
    current_year = date.today().year
    out = [{"keyword": k, "first_year": y, "n": count[k]}
           for k, y in first_year.items() if y >= current_year - 1 and count[k] >= 2]
    out.sort(key=lambda x: (-x["first_year"], -x["n"]))
    return out[:limit]


def infra_cited(conn: sqlite3.Connection, limit: int = 8) -> list[dict]:
    """Obras con muchas referencias pero pocas citas recibidas (fuentes infra-citadas)."""
    rows = conn.execute(
        """SELECT id, title, doi, year, journal_title, cited_by,
                  json_array_length(ifnull(referenced_ids,'[]')) + json_array_length(ifnull(s2_references,'[]')) AS refs
           FROM articles WHERE cited_by < 5
           ORDER BY refs DESC LIMIT 200"""
    ).fetchall()
    out = []
    for r in rows:
        if r["refs"] and r["refs"] >= 10:
            out.append({**dict(r), "refs": r["refs"]})
        if len(out) >= limit:
            break
    return out


def three_questions(conn: sqlite3.Connection) -> dict:
    """Tres preguntas focales deterministas a partir de los vacíos detectados."""
    questions = []
    q = under_explored_pairs(conn, limit=1)
    if q:
        p = q[0]
        questions.append({
            "type": "pair_underexplored",
            "question": (f"¿Por qué «{p['keyword_a']}» y «{p['keyword_b']}» casi nunca "
                         f"co-ocurren en la literatura del campo, pese a que cada una es "
                         f"frecuente por separado? (intersección esperada ≈{p['expected_intersection']}, real {p['actual_cooccurrence']})"),
            "evidence": p,
        })
    d = dense_without_synthesis(conn, limit=1)
    if d:
        t = d[0]
        questions.append({
            "type": "dense_no_synthesis",
            "question": (f"El campo «{t['field']}» acumula {t['articles']} artículos pero apenas "
                         f"{t['synthesis']} síntesis/revisiones: ¿qué estado de la cuestión "
                         f"consolidaría la evidencia dispersa?"),
            "evidence": t,
        })
    e = emerging_keywords(conn, limit=1)
    if e:
        k = e[0]
        questions.append({
            "type": "emerging",
            "question": (f"El término «{k['keyword']}» irrumpió en el catálogo en {k['first_year']} "
                         f"({k['n']} publicaciones): ¿es una línea de investigación emergente o un "
                         f"modismo pasajero del campo?"),
            "evidence": k,
        })
    i = infra_cited(conn, limit=1)
    if i and len(questions) < 3:
        w = i[0]
        questions.append({
            "type": "infra_cited",
            "question": (f"«{w['title'][:80]}…» acumula {w['refs']} referencias pero menos de 5 citas: "
                         f"¿qué infra-citación revela sobre los canales de circulación del campo?"),
            "evidence": w,
        })
    return {"count": len(questions), "questions": questions}