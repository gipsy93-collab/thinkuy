# -*- coding: utf-8 -*-
"""Inteligencia editorial: temas emergentes, captación de revisores, benchmarking y auditoría ecosistémica."""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from .. import config, db
from ..normalize import norm, edit_distance, unescape
from .common import (
    log,
    CC_AUDIT_TTL_HOURS,
    CC_DOMAIN_RANKS_DB,
    KNOWN_JOURNAL_DOMAINS,
    _SCIVIS_RANKING_TTL,
    _clean_domain,
    _split_url_scope,
    _cc_total_domains,
    _get_db_conn,
    _is_portal_host,
    CC_RELEASE_ID,
)
from .commoncrawl import (
    get_latest_common_crawl_collection,
    query_common_crawl_domain_real,
    get_common_crawl_harmonic_centrality,
    get_cc_history_trajectory,
)
from .links import (
    build_conversational_web_graph_analysis,
    build_web_proximity_radar,
    compute_web_twins,
    discover_transmedia_channels,
    audit_in_out_links,
)
from .resolution import resolve_journal_domain_and_meta

def get_local_catalog_metrics(journal_title: str, db_path: str = config.DB_PATH) -> Dict[str, Any]:
    """Obtiene métricas reales y auditables de la revista en el catálogo local SQLite.

    El conteo usa coincidencia EXACTA normalizada del título de la revista; el LIKE por
    substring es solo fallback (un título corto como 'zer' daría falsos positivos por
    substring contra otras revistas)."""
    conn = _get_db_conn(db_path)
    try:
        q_norm = norm(journal_title)
        row = conn.execute(
            """SELECT COUNT(*) as count,
                      COALESCE(SUM(cited_by), 0) as total_cites,
                      MIN(year) as min_year,
                      MAX(year) as max_year
               FROM articles
               WHERE norm(journal_title) = ?""",
            (q_norm,),
        ).fetchone()

        art_count = row[0] if row else 0
        if art_count == 0:
            # Fallback: solo cuando el título exacto no tiene artículos en el catálogo.
            row = conn.execute(
                """SELECT COUNT(*) as count,
                          COALESCE(SUM(cited_by), 0) as total_cites,
                          MIN(year) as min_year,
                          MAX(year) as max_year
                   FROM articles
                   WHERE norm(journal_title) LIKE ?""",
                (f"%{q_norm}%",),
            ).fetchone()
            art_count = row[0] if row else 0
        cites = row[1] if row else 0
        min_y = row[2] if row else None
        max_y = row[3] if row else None

        years_range = f"{min_y} - {max_y}" if (min_y and max_y and min_y != max_y) else str(max_y or "N/D")

        return {
            "articles_count": art_count,
            "total_citations": cites,
            "years_coverage": years_range,
            "has_local_records": art_count > 0,
        }
    finally:
        conn.close()


def get_dominant_and_emerging_topics(
    journal_title: str = "",
    field: str = "",
    db_path: str = config.DB_PATH
) -> Dict[str, Any]:
    """
    Extrae temas dominantes y emergentes a partir de frecuencias reales de palabras clave
    en los artículos indizados en SQLite.
    NO genera palabras clave simuladas: si no hay datos, devuelve listas vacías.
    """
    conn = _get_db_conn(db_path)
    try:
        filter_sql = ""
        params = []
        if journal_title:
            filter_sql = "WHERE (norm(journal_title) LIKE ? OR norm(journal_title) = ?) AND keywords IS NOT NULL AND TRIM(keywords) != ''"
            params.extend([f"%{norm(journal_title)}%", norm(journal_title)])
        elif field:
            filter_sql = "WHERE (norm(title) LIKE ? OR norm(abstract) LIKE ?) AND keywords IS NOT NULL AND TRIM(keywords) != ''"
            params.extend([f"%{norm(field)}%", f"%{norm(field)}%"])
        else:
            filter_sql = "WHERE keywords IS NOT NULL AND TRIM(keywords) != ''"

        rows = conn.execute(
            f"SELECT keywords, year FROM articles {filter_sql} ORDER BY year DESC LIMIT 500",
            params,
        ).fetchall()

        freq: Dict[str, int] = {}
        recent_freq: Dict[str, int] = {}
        # Ventana de recencia desde el dato real del catálogo (nunca un año supuesto).
        years_in_data = [r["year"] for r in rows if r["year"]]
        max_year = max(years_in_data) if years_in_data else 2026

        for r in rows:
            raw = r["keywords"]
            if not raw:
                continue
            y = r["year"] or 2020
            items = []
            if raw.strip().startswith("["):
                try:
                    arr = json.loads(raw)
                    items = [str(x) for x in arr]
                except Exception:
                    items = re.split(r"[,;•|]", raw)
            else:
                items = re.split(r"[,;•|]", raw)

            for item in items:
                term = item.strip().lower()
                if len(term) > 3 and not term.isdigit() and term not in {"none", "null", "article"}:
                    freq[term] = freq.get(term, 0) + 1
                    if y >= max_year - 2:
                        recent_freq[term] = recent_freq.get(term, 0) + 1

        sorted_freq = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        dominant = [t[0].title() for t in sorted_freq[:6]]

        emerging = [
            t[0].title()
            for t in sorted(recent_freq.items(), key=lambda x: x[1], reverse=True)
            if t[0].title() not in dominant[:3] and t[1] >= 2
        ][:5]

        return {
            "dominant_topics": dominant,
            "emerging_topics": emerging,
            "total_keywords_analyzed": len(freq),
        }
    finally:
        conn.close()


def find_editors_and_reviewers(
    topic_or_journal: str,
    limit: int = 5,
    db_path: str = config.DB_PATH
) -> List[Dict[str, Any]]:
    """
    Identifica autores e investigadores reales a partir de los artículos registrados
    en la base de datos local SQLite.
    NO genera autores simulados ni ficticios.
    """
    conn = _get_db_conn(db_path)
    try:
        q_norm = norm(topic_or_journal)
        rows = conn.execute(
            """SELECT authors, title, journal_title, year, cited_by
               FROM articles 
               WHERE (norm(journal_title) LIKE ? 
                  OR norm(keywords) LIKE ? 
                  OR norm(title) LIKE ? 
                  OR norm(abstract) LIKE ?)
                  AND authors IS NOT NULL AND TRIM(authors) != ''
               ORDER BY year DESC, cited_by DESC LIMIT 150""",
            (f"%{q_norm}%", f"%{q_norm}%", f"%{q_norm}%", f"%{q_norm}%"),
        ).fetchall()

        author_map: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            raw = r["authors"]
            names = []
            if raw.strip().startswith("["):
                try:
                    arr = json.loads(raw)
                    for a in arr:
                        if isinstance(a, dict):
                            full = f"{a.get('given', '')} {a.get('family', '')}".strip()
                            if full:
                                names.append(full)
                        elif isinstance(a, str):
                            names.append(a)
                except Exception:
                    pass
            if not names:
                names = [n.strip() for n in re.split(r"[,;]", raw) if len(n.strip()) > 4]

            for name in names[:3]:
                clean_name = re.sub(r"\s+", " ", name).strip()
                # Filtrar nombres inválidos o institucionales
                if len(clean_name) <= 3 or clean_name.lower().startswith("editor") or clean_name.lower().startswith("redacc"):
                    continue
                if clean_name not in author_map:
                    author_map[clean_name] = {
                        "name": clean_name,
                        "articles_count": 0,
                        "recent_year": r["year"],
                        "total_citations": 0,
                        "sample_titles": [],
                        "journals": set(),
                    }
                author_map[clean_name]["articles_count"] += 1
                author_map[clean_name]["total_citations"] += (r["cited_by"] or 0)
                if r["title"] and len(author_map[clean_name]["sample_titles"]) < 2:
                    author_map[clean_name]["sample_titles"].append(r["title"])
                if r["journal_title"]:
                    author_map[clean_name]["journals"].add(r["journal_title"])

        candidates = sorted(
            author_map.values(),
            key=lambda x: (x["articles_count"], x["total_citations"]),
            reverse=True,
        )

        output = []
        for c in candidates[:limit]:
            output.append({
                "name": c["name"],
                "role_suggestion": "Editor de Sección / Revisor Par",
                "articles_count": c["articles_count"],
                "citations": c["total_citations"],
                "recent_year": c["recent_year"] or 2026,
                "sample_papers": c["sample_titles"],
                "journals_published": list(c["journals"])[:2],
                # Sin evaluación de COI fabricada: verificarla requiere información editorial
                # que el catálogo no tiene. Se declara explícitamente como no evaluado.
                "conflict_of_interest_risk": "No evaluado (requiere verificación editorial)",
            })

        return output
    finally:
        conn.close()


def get_competitor_benchmarking(
    category_or_query: str,
    target_journal: str = "",
    limit: int = 6,
    db_path: str = config.DB_PATH
) -> List[Dict[str, Any]]:
    """
    Devuelve revistas comparables reales indizadas en el catálogo local SQLite,
    preferentemente del MISMO área temática (subject_areas del catálogo) que la
    revista objetivo; si no hay área o no hay coincidencias, cae al ranking por
    volumen real de artículos y citas.
    """
    conn = _get_db_conn(db_path)
    try:
        # 1. Filtro por área temática real (subject_areas de journals)
        filter_titles: Optional[List[str]] = None
        cat_tokens = [
            norm(t.strip())
            for t in re.split(r"[,;/&|+]", category_or_query or "")
            if len(t.strip()) >= 3
        ]
        if cat_tokens:
            jrows = conn.execute(
                "SELECT title, subject_areas FROM journals WHERE subject_areas IS NOT NULL AND TRIM(subject_areas) != ''"
            ).fetchall()
            matched = [
                j["title"]
                for j in jrows
                if any(tok in norm(j["subject_areas"]) for tok in cat_tokens)
            ]
            if matched:
                filter_titles = matched

        sql = (
            "SELECT a.journal_title, COUNT(*) as articles_count, "
            "       COALESCE(SUM(a.cited_by), 0) as total_cites, "
            "       MAX(a.year) as latest_year, MIN(a.issn) as issn, "
            "       MIN(a.url) as url "
            "FROM articles a "
            "WHERE a.journal_title IS NOT NULL AND TRIM(a.journal_title) != ''"
        )
        params: list = []
        if filter_titles:
            sql += " AND a.journal_title IN (%s)" % ",".join("?" * len(filter_titles))
            params.extend(filter_titles)
        sql += " GROUP BY a.journal_title ORDER BY articles_count DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()

        # Conexión rápida al índice de rankings para asignar centralidad a los comparables
        cc_conn = None
        if os.path.exists(CC_DOMAIN_RANKS_DB):
            try:
                cc_conn = sqlite3.connect(CC_DOMAIN_RANKS_DB)
                cc_conn.row_factory = sqlite3.Row
            except Exception:
                cc_conn = None

        result = []
        for r in rows:
            title = r["journal_title"]
            is_target = bool(target_journal and norm(target_journal) in norm(title))
            
            # Resolver dominio conocido o desde URL
            dom = None
            for key, kdom in KNOWN_JOURNAL_DOMAINS.items():
                if norm(key) in norm(title):
                    dom = kdom
                    break
            if not dom and r["url"]:
                host = (urllib.parse.urlparse(r["url"]).netloc or "").lower()
                if host and "doi.org" not in host:
                    dom = host

            h_rank = None
            h_val = None
            pr_rank = None
            if dom and cc_conn is not None:
                for cand_norm in _domain_candidates(_clean_domain(dom)):
                    crow = cc_conn.execute(
                        """SELECT domain_norm, harmonic_rank, harmonic_val, pagerank_rank
                           FROM cc_ranks WHERE domain_norm = ? LIMIT 1""",
                        (cand_norm,),
                    ).fetchone()
                    if crow:
                        h_rank = int(crow["harmonic_rank"])
                        h_val = float(crow["harmonic_val"])
                        pr_rank = int(crow["pagerank_rank"]) if crow["pagerank_rank"] else None
                        dom = crow["domain_norm"]
                        break

            result.append({
                "journal_title": title,
                "issn": r["issn"] or "N/D",
                "domain": dom or "",
                "harmonic_rank": h_rank,
                "harmonic_val": h_val,
                "pagerank_rank": pr_rank,
                "target_radius": round(_get_proximity_radius(h_rank), 3) if h_rank else None,
                "articles_count": r["articles_count"],
                "total_citations": r["total_cites"],
                "latest_year": r["latest_year"],
                "is_target": is_target,
                "matched_area": bool(filter_titles),
            })

        if cc_conn is not None:
            cc_conn.close()

        return result
    finally:
        conn.close()


def audit_journal_ecosystem(
    query: str,
    db_path: str = config.DB_PATH,
    refresh: bool = False,
) -> Dict[str, Any]:
    """
    Auditoría cibermétrica y editorial sin simulaciones:
      - Caché TTL (THINKUY_CC_AUDIT_TTL_HOURS, 24 h por defecto); `refresh=True` fuerza medición nueva.
      - Cada auditoría se persiste en `scivis_store` (data/scivis_store.db) para construir una
        serie longitudinal REAL de la propia herramienta.
      - Consulta en vivo al índice CDX oficial de Common Crawl y rankings del Web Graph indexado.
      - Temas, editores y comparables extraídos de datos reales del catálogo SQLite.
    """
    from .. import scivis_store

    if not refresh:
        cached = scivis_store.cache_get(query, ttl_hours=CC_AUDIT_TTL_HOURS)
        if cached:
            em = cached.get("editorial_mapping") or {}
            has_topics = bool((cached.get("topics") or {}).get("dominant_topics") or (cached.get("topics") or {}).get("emerging_topics"))
            if "editorial_mapping" not in cached or (not em.get("found") and not has_topics):
                cached = None
            else:
                if "proximity_radar" not in cached:
                    cached["proximity_radar"] = build_web_proximity_radar(
                        cached.get("harmonic_centrality") or {},
                        cached.get("journal_title") or query,
                        cached.get("domain") or "",
                        competitors=cached.get("competitors"),
                    )
                cached["served_from_cache"] = True
                cached["cached_at"] = time.time()
                return cached

    domain, meta = resolve_journal_domain_and_meta(query, db_path=db_path)
    journal_title = meta.get("journal_title") or query

    # 1. Consulta en tiempo real a Common Crawl CDX (con alcance de revista si la URL lo traía)
    cc_result = query_common_crawl_domain_real(domain, scope_path=meta.get("journal_path")) if domain else {
        "verified": False,
        "status": "Dominio no disponible para consulta",
        "error": "No se cuenta con el dominio web de esta publicación para consultar Common Crawl.",
    }

    # 2. Centralidad Armónica y PageRank oficiales de Common Crawl
    harmonic_data = get_common_crawl_harmonic_centrality(domain) if domain else {
        "available": False,
        "status": "Dominio no disponible",
        "harmonic_val": None,
        "harmonic_rank": None,
        "pagerank_val": None,
        "pagerank_rank": None,
    }

    # 2b. Análisis cibermétrico conversacional CALIBRADO (unidad medida + lenguaje por tier)
    shared_at_build = bool(meta.get("shared_host")) or _is_portal_host(domain or "")
    web_analysis = build_conversational_web_graph_analysis(
        harmonic_data,
        journal_title,
        domain or "",
        shared_host=shared_at_build,
        journal_segment=meta.get("journal_segment"),
    )
    harmonic_data["analysis"] = web_analysis

    # 3. Métricas del catálogo local
    local_stats = get_local_catalog_metrics(journal_title, db_path=db_path)

    # 4. Mapeo Bibliométrico de Oportunidades Temáticas (OpenAlex Topics) y Autores ORCID
    from .. import editorial_radar
    target_ident = meta.get("issn") if (meta.get("issn") and meta.get("issn") != "N/D") else (journal_title or query)
    editorial_res = editorial_radar.run_editorial_bibliometric_mapping(
        target_ident,
        journal_title=journal_title or query,
        max_topics=6,
        authors_per_topic=3
    )

    topics = {
        "dominant_topics": [],
        "emerging_topics": [],
        "gap_topics": [],
        "raw_consolidated": [],
        "raw_emerging": [],
        "raw_gaps": [],
    }
    if editorial_res.get("found"):
        topics["dominant_topics"] = [
            f"{t['name']}" for t in editorial_res.get("consolidated_topics", [])
        ]
        topics["emerging_topics"] = [
            f"{t['name']}" for t in editorial_res.get("emerging_topics", [])
        ]
        topics["gap_topics"] = [
            f"{t['name']}" for t in editorial_res.get("gap_topics", [])
        ]
        topics["raw_consolidated"] = editorial_res.get("consolidated_topics", [])
        topics["raw_emerging"] = editorial_res.get("emerging_topics", [])
        topics["raw_gaps"] = editorial_res.get("gap_topics", [])

    # Fallback al catálogo local si OpenAlex no tenía topics asignados
    if not topics["dominant_topics"] and not topics["emerging_topics"]:
        local_topics = get_dominant_and_emerging_topics(journal_title=journal_title, db_path=db_path)
        if not local_topics.get("dominant_topics"):
            local_topics = get_dominant_and_emerging_topics(field=query, db_path=db_path)
        topics["dominant_topics"] = local_topics.get("dominant_topics") or []
        topics["emerging_topics"] = local_topics.get("emerging_topics") or []

    # 5. Editores y revisores reales con ORCID verificado
    if editorial_res.get("found") and editorial_res.get("suggested_reviewers"):
        reviewers = editorial_res.get("suggested_reviewers")
    else:
        reviewers = find_editors_and_reviewers(journal_title, limit=5, db_path=db_path)
        if not reviewers and query != journal_title:
            reviewers = find_editors_and_reviewers(query, limit=5, db_path=db_path)

    # 6. Revistas comparables en el catálogo
    competitors = get_competitor_benchmarking(
        category_or_query=meta.get("category", ""),
        target_journal=journal_title,
        limit=6,
        db_path=db_path,
    )

    methodology_note = (
        f"La Centralidad Armónica y PageRank reportados provienen del análisis del hipergrafo "
        f"de la web de Common Crawl (Release oficial {CC_RELEASE_ID}). "
        "Por rigor metodológico y transparencia, Thinkuy no simula valores: consulta las capturas en vivo del índice CDX "
        "y el índice local de rankings de dominios de Common Crawl."
    )

    # 2c. Auditoría Hipertextual: In-Links vs. Out-Links, Trayectoria Real y Consultoría UCC+I
    in_out_audit = audit_in_out_links(
        domain=domain or "",
        journal_title=journal_title,
        harmonic_data=harmonic_data,
        openalex_meta=meta,
        journal_segment=meta.get("journal_segment"),
        shared_host_catalog=bool(meta.get("shared_host")),
    )

    # Señal combinada de portal compartido (catálogo local + evidencia empírica de Wikipedia).
    shared_host = bool(meta.get("shared_host") or in_out_audit.get("host_is_shared"))
    # Si la evidencia empírica reveló compartido DESPUÉS de construir la narrativa, añadir
    # la advertencia (sin duplicar si ya iba integrada en el análisis calibrado).
    if shared_host and not shared_at_build and web_analysis and web_analysis.get("summary_paragraphs"):
        web_analysis["summary_paragraphs"].append(
            f"Aviso de atribución: '{meta.get('domain')}' es un portal institucional compartido que aloja varias "
            "revistas; la Centralidad Armónica y el PageRank corresponden a todo el portal, no solo a esta publicación."
        )

    result = {
        "mode": "journal_audit",
        "query": query,
        "journal_title": journal_title,
        "domain": domain or "N/D",
        "domain_resolution": meta.get("resolution"),
        "shared_host": shared_host,
        "ambiguous": bool(meta.get("ambiguous")),
        "ambiguous_matches": meta.get("ambiguous_matches") or [],
        "issn": meta.get("issn", "N/D"),
        "category": meta.get("category", "General"),
        "country": meta.get("country", "N/D"),
        "publisher": meta.get("publisher", "N/D"),
        "global_stats": {
            "works_count": meta.get("global_works"),
            "cited_by_count": meta.get("global_cites"),
            "h_index": meta.get("h_index"),
        },
        "common_crawl": cc_result,
        "harmonic_centrality": harmonic_data,
        "web_graph_analysis": web_analysis,
        "proximity_radar": build_web_proximity_radar(harmonic_data, journal_title, domain or "", competitors=competitors),
        "in_out_audit": in_out_audit,
        "local_stats": local_stats,
        "methodology_note": methodology_note,
        "competitors": competitors,
        "topics": topics,
        "suggested_editors": reviewers,
        "editorial_mapping": editorial_res,
        "served_from_cache": False,
        "audit_timestamp": time.time(),
        "release": CC_RELEASE_ID,
    }
    scivis_store.cache_put(result)
    return result


_SCIVIS_RANKING_CACHE: Dict[str, Any] = {}


def get_scivis_ranking(limit: int = 15, db_path: str = config.DB_PATH) -> List[Dict[str, Any]]:
    """
    Ranking cibermétrico SCIVIS: revistas del catálogo ordenadas por su Centralidad
    Armónica oficial en el Web Graph de Common Crawl (mejor rank primero).
    Solo se listan revistas con dato real del release indexado; las que no figuran
    se excluyen explícitamente (nunca se les asigna un rank estimado).
    Resultado memoizado 1 h (el release no cambia entre consultas).
    """
    global _SCIVIS_RANKING_CACHE
    cache_key = f"{db_path}:{CC_DOMAIN_RANKS_DB}"
    cached = _SCIVIS_RANKING_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _SCIVIS_RANKING_TTL:
        return [dict(x) for x in cached[1]][:limit]

    conn = _get_db_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT a.journal_title, COUNT(*) as articles_count,
                      COALESCE(SUM(a.cited_by), 0) as total_cites,
                      MIN(a.issn) as issn, MIN(a.url) as url
               FROM articles a
               WHERE a.journal_title IS NOT NULL AND TRIM(a.journal_title) != ''
               GROUP BY a.journal_title
               ORDER BY articles_count DESC LIMIT 400"""
        ).fetchall()
    finally:
        conn.close()

    def _local_domain(title: str, url: str) -> Optional[str]:
        for key, dom in KNOWN_JOURNAL_DOMAINS.items():
            if norm(key) in norm(title):
                return dom
        if url:
            host = (urllib.parse.urlparse(url).netloc or "").lower()
            if host and "doi.org" not in host:
                return host
        return None

    # Una sola conexión al índice de rankings para todo el lote.
    cc_conn = None
    try:
        if os.path.exists(CC_DOMAIN_RANKS_DB):
            cc_conn = sqlite3.connect(CC_DOMAIN_RANKS_DB)
            cc_conn.row_factory = sqlite3.Row
        ranked: List[Dict[str, Any]] = []
        total_domains = _cc_total_domains(CC_DOMAIN_RANKS_DB)
        for r in rows:
            dom = _local_domain(r["journal_title"], r["url"] or "")
            if not dom or cc_conn is None:
                continue
            row = None
            for cand_norm in _domain_candidates(_clean_domain(dom)):
                row = cc_conn.execute(
                    """SELECT domain_norm, harmonic_rank, harmonic_val, pagerank_rank, pagerank_val
                       FROM cc_ranks WHERE domain_norm = ? LIMIT 1""",
                    (cand_norm,),
                ).fetchone()
                if row:
                    break
            if not row:
                continue
            hrank = int(row["harmonic_rank"])
            ranked.append({
                "journal_title": r["journal_title"],
                "issn": r["issn"] or "N/D",
                "domain": row["domain_norm"],
                "harmonic_rank": hrank,
                "harmonic_val": row["harmonic_val"],
                "pagerank_rank": row["pagerank_rank"],
                "pagerank_val": row["pagerank_val"],
                "percentile_top": round((hrank / (total_domains or 58_900_000)) * 100, 4),
                "articles_count": r["articles_count"],
                "total_citations": r["total_cites"],
                "release": CC_RELEASE_ID,
            })
        ranked.sort(key=lambda x: x["harmonic_rank"])
        result = ranked[:limit]
    finally:
        if cc_conn is not None:
            cc_conn.close()

    _SCIVIS_RANKING_CACHE[cache_key] = (time.time(), result)
    return result

