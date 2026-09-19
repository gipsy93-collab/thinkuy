"""Subrouter de la API de Thinkuy."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from ... import author_match, db, network, profile, quality, topics
from ...citations import citation_filename, format_citation
from ...conversation import rank_conversation, score_article, why_labels
from ...matching import match_article, parse_keywords, rank_articles
from ..common import (
    _date_int,
    _field_profile,
    _query_articles,
    _safe_doi,
    _widget_card,
    _with_display_keywords,
)

router = APIRouter(tags=['feed'])
log = logging.getLogger('radar.api.feed')

@router.get("/api/feed")
def feed(
    keywords: str = Query("", description="Keywords separadas por coma"),
    journal: str = Query("", description="Nombre o fragmento de la revista"),
    langs: str = Query("", description="Idiomas separados por coma: es,pt,en"),
    sources: str = Query("", description="Fuentes separadas por coma: scielo,crossref,openalex,redalyc"),
    limit: int = Query(20, ge=1, le=100),
    days: int = Query(3650, ge=1, le=7300),
    sort: str = Query("relevance", pattern="^(relevance|recent|cited)$",
                      description="relevance=score+prominencia, recent=más recientes, cited=más citados"),
    quality_mode: str = Query("auto", pattern="^(auto|high|all)$",
                              description="auto=Q1/Q2 y si no hay, cascada a Q3/Q4/sin clasificar; high=solo Q1/Q2; all=todos"),
    show_all: bool = Query(False, description="Ignorar keywords y devolver los más recientes"),
):
    conn = db.connect()
    try:
        kw_list = parse_keywords(keywords)
        lang_list = [l.strip().lower() for l in langs.split(",") if l.strip()]
        src_list = [s.strip().lower() for s in sources.split(",") if s.strip()]
        has_kw = bool(kw_list) and not show_all
        # Si hay keywords o revista específica, evaluar el catálogo relevante (sin corte artificial)
        max_rows = None if (has_kw or journal) else 800
        arts = _query_articles(conn, days, lang_list, src_list, order=sort, max_rows=max_rows, journal=journal)
        if has_kw:
            ranked = rank_articles(arts, kw_list)
            ranked = [a for a in ranked if a["match_score"] > 0]
        else:
            ranked = arts
            for a in ranked:
                a.setdefault("match_score", 0)
                a.setdefault("matched", [])

        # Calidad editorial: anotar cuartil SJR de cada artículo (del catálogo de revistas)
        qmap_issn, qmap_title = quality.build_tier_map(conn)
        for a in ranked:
            a["quartile"] = quality.tier_of_article(a, qmap_issn, qmap_title)
            a["quality_boost"] = quality.QUALITY_BONUS.get(a["quartile"], 0)

        # Cascada de calidad: auto → Q1/Q2; si vacío, baja a Q3 → Q4 → sin clasificar.
        quality_band = "all"
        if quality_mode == "high":
            ranked = [a for a in ranked if a.get("quartile") in ("Q1", "Q2")]
            quality_band = "high_q1_q2"
        elif quality_mode == "auto":
            bands = [
                (("Q1", "Q2"), "q1_q2"),
                (("Q3",), "q3"),
                (("Q4",), "q4"),
                ((None,), "sin_clasificar"),
            ]
            for allowed, band_name in bands:
                filtered = [a for a in ranked if a.get("quartile") in allowed]
                if filtered:
                    ranked = filtered
                    quality_band = band_name
                    break
            else:
                ranked = []

        # Jerarquización explícita (relevance ya está ordenado por rank_articles;
        # el cuartil suma prominencia solo entre resultados equivalentes).
        if sort == "recent":
            ranked.sort(key=lambda a: (a.get("pub_date") or "", a.get("doi") or ""), reverse=True)
        elif sort == "cited":
            ranked.sort(key=lambda a: (a.get("cited_by") or 0, a.get("pub_date") or ""), reverse=True)
        else:
            ranked.sort(key=lambda a: (
                -((a.get("match_score") or 0) + quality.QUALITY_BONUS.get(a.get("quartile"), 0)),
                -_date_int(a.get("pub_date")),
                a.get("doi") or "",
            ))
        ranked = ranked[:limit]
        profile_data = _field_profile(conn)
        for a in ranked:
            sig = score_article(a, profile_data)
            a["conversation"] = {**sig, "why": why_labels(sig, "es")}
            a["thematic_fields"] = topics.classify_article_fields(a)
            a.pop("referenced_ids", None)
        _with_display_keywords(ranked, candidate_terms=kw_list, limit=6)

        # Ayuda cuando no hay resultados: ¿existen en una ventana más amplia (sin filtros)?
        hints = None
        if not ranked and kw_list and days < 365:
            arts_year = _query_articles(conn, 365, [], [], order=sort, max_rows=None)
            counts = []
            for kw in kw_list:
                n = sum(1 for a in arts_year if match_article(a, [kw])["score"] > 0)
                counts.append({"keyword": kw, "count": n})
            hints = {"wider_window": {"days": 365, "keyword_counts": counts}}

        return {
            "query": {"keywords": kw_list, "journal": journal, "langs": lang_list, "sources": src_list,
                      "days": days, "limit": limit, "sort": sort,
                      "quality_mode": quality_mode},
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(ranked),
            "quality_band": quality_band,
            "hints": hints,
            "articles": ranked,
        }
    finally:
        conn.close()


@router.get("/api/articles/{doi:path}/citation")
def citation(doi: str, format: str = Query("apa", pattern="^(apa|bibtex|ris)$")):
    conn = db.connect()
    try:
        a = db.get_article(conn, _safe_doi(doi))
        if not a:
            raise HTTPException(404, "Artículo no encontrado")
        text = format_citation(a, format)
        fname = citation_filename(a, format)
        return Response(
            content=text,
            media_type={"apa": "text/plain; charset=utf-8",
                        "bibtex": "application/x-bibtex; charset=utf-8",
                        "ris": "application/x-research-info-systems; charset=utf-8"}[format],
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    finally:
        conn.close()


@router.get("/api/articles/{doi:path}")
def article(doi: str):
    """Metadatos completos del artículo en JSON (incluye keywords, autores y matched)."""
    conn = db.connect()
    try:
        a = db.get_article(conn, _safe_doi(doi))
        if not a:
            raise HTTPException(404, "Artículo no encontrado")

        # Hidratación bajo demanda si falta el abstract (Dialnet)
        if not a.get("abstract") and a.get("url"):
            u = str(a.get("url") or "")
            if "dialnet.unirioja.es" in u:
                try:
                    from ...harvester import dialnet
                    det = dialnet.fetch_article_details(u)
                    if det.get("abstract"):
                        a["abstract"] = det["abstract"]
                        conn.execute("UPDATE articles SET abstract = ? WHERE id = ?", (det["abstract"], a["id"]))
                        conn.commit()
                    if det.get("doi") and not a.get("doi"):
                        a["doi"] = det["doi"]
                        conn.execute("UPDATE articles SET doi = ? WHERE id = ?", (det["doi"], a["id"]))
                        conn.commit()
                except Exception as ex:
                    log.debug("No se pudo hidratar abstract de Dialnet para art %s: %s", a.get("id"), ex)

        _with_display_keywords([a])
        return JSONResponse(a, media_type="application/json; charset=utf-8")
    finally:
        conn.close()


@router.get("/api/cfp")
def cfp():
    return {
"field": profile.field_profile.name,
                "cfps": profile.field_profile.cfps,
                "cfp": profile.field_profile.first_cfp(),
                "axes": profile.field_profile.editorial_axes,
    }


@router.get("/api/widget")
def widget_feed(
    mode: str = Query("conversation", pattern="^(conversation|cfp|latest)$"),
    lang: str = Query("es", pattern="^(es|en)$"),
    limit: int = Query(5, ge=1, le=10),
    days: int = Query(365, ge=30, le=3650),
):
    """Payload compacto para el embed OJS: papers en conversación con el corpus."""
    conn = db.connect()
    try:
        profile_data = _field_profile(conn)
        arts = _query_articles(conn, days, [], [], order="pub_date", max_rows=500)
        ranked = rank_conversation(arts, profile_data, mode=mode)[:limit]
        cfp = profile.field_profile.first_cfp()
        return {
            "field": profile.field_profile.name,
            "mode": mode,
            "lang": lang,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cfp": {
                "title": cfp["title_en"] if lang == "en" else cfp["title_es"],
                "period": cfp["period_en"] if lang == "en" else cfp["period_es"],
                "url": cfp["url_en"] if lang == "en" else cfp["url"],
            } if cfp else None,
            "radar_url": "/app/",
            "corpus": {"anchor_articles": profile_data.get("n_works") or 0},
            "count": len(ranked),
            "articles": [_widget_card(a, lang) for a in ranked],
        }
    finally:
        conn.close()


@router.get("/api/sources")
def sources_status():
    conn = db.connect()
    try:
        out = {}
        for s in ("latindex", "scielo", "redalyc", "crossref", "openalex", "core", "europepmc", "enrich", "openalex_live", "crossref_live"):
            lh = db.last_harvest(conn, s)
            out[s] = lh or {"status": "never"}
        return {"sources": out}
    finally:
        conn.close()


@router.get("/api/journals")
def journals(q: str = "", limit: int = Query(50, le=500)):
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM journals WHERE title LIKE ? ORDER BY title LIMIT ?",
            (f"%{q}%", limit),
        ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            try:
                d["subject_areas"] = json.loads(d.get("subject_areas") or "[]")
            except json.JSONDecodeError:
                d["subject_areas"] = []
            out.append(d)
        return {"count": len(out), "journals": out}
    finally:
        conn.close()


@router.get("/api/stats")
def stats():
    conn = db.connect()
    try:
        st = db.stats(conn)
        by_source = {}
        for r in conn.execute("SELECT source, COUNT(*) n FROM journals GROUP BY source").fetchall():
            by_source[r["source"]] = r["n"]
        st["journals_by_source"] = by_source
        return st
    finally:
        conn.close()


@router.get("/api/suggest")
def suggest(q: str = "", limit: int = Query(12, le=30)):
    conn = db.connect()
    try:
        return {"keywords": db.suggest_keywords(conn, q, limit)}
    finally:
        conn.close()


@router.get("/api/topics/trending")
def trending_topics(limit: int = Query(18, ge=1, le=50)):
    """Temas y descriptores más frecuentes en el corpus."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT kw, n FROM keywords_flat
               WHERE length(trim(kw)) >= 3
               ORDER BY n DESC, kw ASC LIMIT ?""",
            (limit * 2,),
        ).fetchall()
        seen = set()
        topics = []
        for r in rows:
            name = (r["kw"] or "").strip()
            key = name.lower()
            if key and key not in seen and len(name) >= 3:
                seen.add(key)
                topics.append({"topic": name, "count": r["n"]})
                if len(topics) >= limit:
                    break
        return {"topics": topics}
    finally:
        conn.close()


@router.get("/api/authors")
def authors(sort: str = Query("new", pattern="^(new|emerging|active)$"),
            days: int = Query(365, ge=1, le=3650),
            limit: int = Query(10, ge=1, le=50)):
    """Autores: 'new' = primera publicación en la ventana; 'emerging' = nueva + ≥2 artículos;
    'active' = con más publicaciones en la ventana. Señales calculadas sobre el catálogo."""
    conn = db.connect()
    try:
        since = (date.today() - timedelta(days=days)).isoformat()
        if sort == "emerging":
            rows = conn.execute(
                """SELECT * FROM author_stats
                   WHERE first_pub_date >= ? AND n >= 2
                   ORDER BY first_pub_date DESC, n DESC LIMIT ?""",
                (since, limit),
            ).fetchall()
        elif sort == "active":
            rows = conn.execute(
                """SELECT * FROM author_stats
                   WHERE last_pub_date >= ? AND n >= 2
                   ORDER BY n DESC, last_pub_date DESC LIMIT ?""",
                (since, limit),
            ).fetchall()
        else:  # new
            rows = conn.execute(
                """SELECT * FROM author_stats
                   WHERE first_pub_date >= ?
                   ORDER BY first_pub_date DESC LIMIT ?""",
                (since, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["journals"] = json.loads(d.get("journals") or "[]")
            except json.JSONDecodeError:
                d["journals"] = []
            out.append(d)
        return {"sort": sort, "days": days, "count": len(out), "authors": out}
    finally:
        conn.close()


@router.get("/api/topics")
def topics_list():
    """Campos canónicos de conocimiento del perfil activo."""
    return {"field": profile.field_profile.name, "fields": topics.fields()}


@router.get("/api/anchors/articles")
def anchor_articles():
    """Lista los artículos del corpus de referencia para selección rápida de autor."""
    conn = db.connect()
    try:
        articles = author_match.list_anchor_articles(conn)
        return {"count": len(articles), "articles": articles}
    finally:
        conn.close()


@router.get("/api/authors/suggest")
def suggest_authors(q: str = Query(..., min_length=2, description="Texto para buscar autor"),
                    limit: int = Query(10, ge=1, le=30)):
    """Busca autores en el catálogo para autocompletar adición al radar."""
    conn = db.connect()
    try:
        net_data = network.build_author_edges(conn, min_works=1)
        authors = net_data.get("authors", {})
        query_text = q.strip()
        query_norm = network.norm(query_text)
        query_orcid_digits = re.sub(r"[^0-9X]", "", query_text.upper())
        matches = []
        for key, info in authors.items():
            name_norm = network.norm(info.get("name", ""))
            orcid_digits = re.sub(r"[^0-9X]", "", (info.get("orcid") or "").upper())
            orcid_match = bool(query_orcid_digits) and bool(orcid_digits) and query_orcid_digits in orcid_digits
            if query_norm in key or query_norm in name_norm or orcid_match:
                matches.append({
                    "key": key,
                    "name": info.get("name") or key,
                    "orcid": info.get("orcid"),
                    "identity_status": info.get("identity_status", "unverified"),
                    "sector": info.get("sector"),
                    "n": info.get("n", 1),
                })
        matches.sort(key=lambda a: (-a["n"], a["name"]))
        return {"q": q, "authors": matches[:limit]}
    finally:
        conn.close()

