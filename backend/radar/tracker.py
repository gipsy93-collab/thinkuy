#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
radar/tracker.py — Rastreador de impacto y difusion granular de DOIs en la web abierta.

Consulta fuentes sin APIs comerciales de pago y devuelve tanto metricas agregadas
como desgloses granulares (papers citantes, articulos de Wikipedia con snippets,
hilos de discusion tecnica, politicas publicas y capturas historicas).
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .normalize import clean_doi

log = logging.getLogger("radar.tracker")

# Ruta absoluta (antes era relativa al CWD: la base se creaba en `data/` o en `backend/data/`
# según desde dónde se ejecutara el script). Sobrescribible con THINKUY_DOI_TRACKER_DB.
DB_PATH = Path(os.environ.get("THINKUY_DOI_TRACKER_DB", config.DATA_DIR / "doi_tracker.db"))
UA = getattr(config, "USER_AGENT", "radar-obcc/1.0 (rastreo de menciones DOI)")


def get_json(url: str, timeout: int = 25, headers: dict | None = None) -> dict | list | None:
    """Peticion HTTP con soporte transparente para GZIP y manejo de errores."""
    h = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }
    if url.startswith("https://api.openalex.org") and getattr(config, "OPENALEX_API_KEY", ""):
        h["Authorization"] = f"Bearer {config.OPENALEX_API_KEY}"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw_data = r.read()
            is_gzip = r.headers.get("Content-Encoding") == "gzip" or (
                len(raw_data) >= 2 and raw_data[:2] == b"\x1f\x8b"
            )
            if is_gzip:
                raw_data = gzip.decompress(raw_data)
            return json.loads(raw_data.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:
        raise


def get_openalex_details(doi: str) -> tuple[int, dict]:
    """Obtiene citas y la lista granular de los ultimos papers que citan al DOI."""
    try:
        canonical_doi = "https://doi.org/" + doi
        url = f"https://api.openalex.org/works/{urllib.parse.quote(canonical_doi, safe='')}"
        work = get_json(url)
        if not work or not isinstance(work, dict):
            return 0, {"info": "DOI no indexado en OpenAlex"}

        work_id = work.get("id", "").split("/")[-1]
        cited_by_count = work.get("cited_by_count", 0)

        citing_papers = []
        if work_id and cited_by_count > 0:
            try:
                citing_url = f"https://api.openalex.org/works?filter=cites:{work_id}&per-page=10&sort=publication_year:desc"
                citing_data = get_json(citing_url)
                if citing_data and isinstance(citing_data, dict):
                    for item in citing_data.get("results", []):
                        authors = [
                            a.get("author", {}).get("display_name")
                            for a in item.get("authorships", [])[:3]
                            if a.get("author", {}).get("display_name")
                        ]
                        source_obj = (item.get("primary_location") or {}).get("source") or {}
                        source_title = source_obj.get("display_name")
                        citing_papers.append({
                            "title": item.get("title"),
                            "year": item.get("publication_year"),
                            "journal": source_title or "Publicación",
                            "authors": authors,
                            "doi": item.get("doi"),
                            "is_oa": (item.get("open_access") or {}).get("is_oa", False),
                            "oa_url": (item.get("open_access") or {}).get("oa_url"),
                        })
            except Exception as e:
                log.warning("Error obteniendo papers citantes de OpenAlex: %s", e)

        return cited_by_count, {
            "title": work.get("title"),
            "year": work.get("publication_year"),
            "cited_by_count": cited_by_count,
            "is_oa": (work.get("open_access") or {}).get("is_oa", False),
            "oa_url": (work.get("open_access") or {}).get("oa_url"),
            "citing_papers": citing_papers,
        }
    except Exception as e:
        return 0, {"error": str(e)[:100]}


def get_wikipedia_details(doi: str) -> tuple[int, list]:
    """Obtiene menciones exactas en Wikipedia (EN + ES) con snippets y enlaces directos."""
    queries = [doi]
    if "arxiv" in doi.lower():
        queries.append(doi.split("/")[-1])

    best_total = 0
    all_details = []

    for lang in ["en", "es"]:
        # 1. Busqueda en el indice de URLs externas (exacto)
        try:
            url_ext = (
                f"https://{lang}.wikipedia.org/w/api.php?action=query&list=exturlusage"
                f"&euquery={urllib.parse.quote('doi.org/' + doi, safe='/')}&format=json&eulimit=10"
            )
            d_ext = get_json(url_ext)
            if d_ext and isinstance(d_ext, dict):
                hits = d_ext.get("query", {}).get("exturlusage", [])
                for h in hits:
                    title = h.get("title", "")
                    if title:
                        all_details.append({
                            "wiki": lang.upper(),
                            "title": title,
                            "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                            "snippet": f"Citado como enlace externo en {title}",
                        })
        except Exception as e:
            log.debug("Error en Wikipedia exturlusage %s: %s", lang, e)

        # 2. Busqueda de texto completo con comillas exactas
        for q in queries:
            try:
                exact_query = f'"{q}"'
                url = (
                    f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search"
                    f"&srsearch={urllib.parse.quote(exact_query)}&format=json&srlimit=8"
                )
                d = get_json(url)
                if d and isinstance(d, dict):
                    res = d.get("query", {}).get("search", [])
                    total_hits = d.get("query", {}).get("searchinfo", {}).get("totalhits", len(res))
                    best_total += total_hits
                    for x in res:
                        title = x.get("title", "")
                        clean_snippet = re.sub(r"<[^>]+>", "", x.get("snippet", ""))
                        all_details.append({
                            "wiki": lang.upper(),
                            "title": title,
                            "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                            "snippet": clean_snippet[:140],
                        })
            except Exception as e:
                log.debug("Error consultando Wikipedia %s: %s", lang, e)
            time.sleep(0.15)

    seen, uniq = set(), []
    for it in all_details:
        key = (it.get("wiki"), it.get("title"))
        if it.get("title") and key not in seen:
            seen.add(key)
            uniq.append(it)

    return len(uniq), uniq[:8]


def get_hackernews_details(doi: str, title: str = "") -> tuple[int, list]:
    """Hacker News via Algolia con hilos y enlaces directos."""
    queries = [f'"{doi}"']
    if "arxiv" in doi.lower():
        queries.append(f'"{doi.split("/")[-1]}"')
    if title and len(title.strip()) > 8:
        queries.append(f'"{title.strip()}"')

    detail = []
    seen = set()

    for q in queries:
        try:
            d = get_json(
                f"https://hn.algolia.com/api/v1/search?query={urllib.parse.quote(q)}&hitsPerPage=8&tags=story"
            )
            if d and isinstance(d, dict):
                for h in d.get("hits", []):
                    story_id = h.get("objectID")
                    if story_id and story_id not in seen:
                        seen.add(story_id)
                        detail.append({
                            "title": (h.get("title") or "")[:100],
                            "author": h.get("author", ""),
                            "points": h.get("points", 0),
                            "num_comments": h.get("num_comments", 0),
                            "date": (h.get("created_at") or "")[:10],
                            "url": h.get("url") or (f"https://news.ycombinator.com/item?id={story_id}" if story_id else None),
                            "hn_url": f"https://news.ycombinator.com/item?id={story_id}" if story_id else None,
                        })
        except Exception as e:
            log.debug("Error consultando HN: %s", e)
        time.sleep(0.15)

    return len(detail), detail[:6]


def get_stackexchange_details(doi: str, title: str = "") -> tuple[int, list]:
    """Preguntas en StackOverflow / StackExchange con enlaces."""
    queries = [f'"{doi}"']
    if "arxiv" in doi.lower():
        queries.append(f'"{doi.split("/")[-1]}"')

    all_items = []
    seen = set()

    for q in queries:
        try:
            url = f"https://api.stackexchange.com/2.3/search/excerpts?q={urllib.parse.quote(q)}&site=stackoverflow&pagesize=6"
            d = get_json(url)
            if d and isinstance(d, dict):
                for it in d.get("items", []):
                    q_id = it.get("question_id")
                    if q_id and q_id not in seen:
                        seen.add(q_id)
                        all_items.append({
                            "title": (it.get("title") or "")[:100],
                            "url": f"https://stackoverflow.com/questions/{q_id}" if q_id else None,
                            "score": it.get("score", 0),
                        })
        except Exception as e:
            log.debug("Error consultando SE: %s", e)
        time.sleep(0.15)

    return len(all_items), all_items[:6]


def get_altmetric_details(doi: str) -> tuple[int, dict]:
    """Endpoint publico de Altmetric con metricas de impacto social y politicas publicas."""
    try:
        url = f"https://api.altmetric.com/v1/doi/{urllib.parse.quote(doi, safe='')}"
        d = get_json(url)
        if not d or not isinstance(d, dict):
            return 0, {"info": "Sin registro público en Altmetric"}

        score = int(round(d.get("score", 0)))
        return score, {
            "score": d.get("score"),
            "tweets": d.get("cited_by_tweeters_count", 0),
            "news": d.get("cited_by_msm_count", 0),
            "policies": d.get("cited_by_policies_count", 0),
            "wikipedia": d.get("cited_by_wikipedia_count", 0),
            "blogs": d.get("cited_by_feeds_count", 0),
            "details_url": d.get("details_url"),
        }
    except Exception as e:
        return 0, {"error": str(e)[:100]}


def get_wayback_details(doi: str) -> tuple[int, list]:
    """Capturas historicas en Wayback Machine."""
    try:
        url = (
            f"http://web.archive.org/cdx/search/cdx?url="
            f"{urllib.parse.quote('doi.org/' + doi, safe='/')}&matchType=prefix&output=json&fl=timestamp,statuscode&limit=500"
        )
        d = get_json(url)
        if not d or not isinstance(d, list) or len(d) < 2:
            return 0, []
        rows = d[1:]
        detail = [{"timestamp": r[0], "status": r[1]} for r in rows[-5:]]  # Ultimas 5 capturas
        return len(rows), detail
    except Exception as e:
        return 0, [{"error": str(e)[:100]}]


def get_crossref_details(doi: str) -> tuple[int, dict]:
    """Citas formales en Crossref."""
    try:
        url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='/')}"
        d = get_json(url)
        if not d or not isinstance(d, dict):
            return 0, {"info": "No registrado en Crossref"}
        msg = d.get("message", {})
        return msg.get("is-referenced-by-count", 0), {
            "title": (msg.get("title") or [""])[0],
            "is_referenced_by_count": msg.get("is-referenced-by-count", 0),
        }
    except Exception:
        return 0, {"info": "No registrado en Crossref"}


# Feeds transmedia de revistas, blogs científicos y newsletters
TRANSMEDIA_FEEDS = [
    ("Revista Panamericana de Pedagogía", "https://revpanamericanadepedagogia.substack.com/feed"),
]


def get_transmedia_blog_details(doi: str, title: str = "") -> tuple[int, list]:
    """Rastrea menciones, notas divulgativas y adaptaciones transmedia en Substack, blogs y newsletters científicas."""
    import xml.etree.ElementTree as ET
    doi_norm = doi.lower().strip()
    doi_tail = doi_norm.split("/")[-1] if "/" in doi_norm else doi_norm
    title_norm = title.lower().strip() if title else ""
    title_keywords = [w for w in re.findall(r"\w+", title_norm) if len(w) > 4][:4]

    matches = []
    seen = set()

    for pub_name, feed_url in TRANSMEDIA_FEEDS:
        try:
            req = urllib.request.Request(feed_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=12) as r:
                root = ET.fromstring(r.read())
                for item in root.findall(".//item"):
                    i_title = (item.find("title").text if item.find("title") is not None else "") or ""
                    i_link = (item.find("link").text if item.find("link") is not None else "") or ""
                    i_date = (item.find("pubDate").text if item.find("pubDate") is not None else "") or ""
                    i_desc = (item.find("description").text if item.find("description") is not None else "") or ""
                    i_content = ""
                    for child in item:
                        if "encoded" in child.tag:
                            i_content = child.text or ""

                    full_text = f"{i_title} {i_desc} {i_content}".lower()

                    is_match = False
                    if (
                        doi_norm in full_text
                        or (len(doi_tail) >= 4 and f"/{doi_tail}" in full_text)
                        or f"rpp.{doi_tail}" in full_text
                        or f"view/{doi_tail}" in full_text
                    ):
                        is_match = True
                    elif title_keywords and sum(1 for kw in title_keywords if kw in full_text) >= max(2, len(title_keywords) - 1):
                        is_match = True

                    if is_match and i_link not in seen:
                        seen.add(i_link)
                        clean_snippet = re.sub(r"<[^>]+>", " ", i_desc or i_content).strip()
                        clean_snippet = " ".join(clean_snippet.split())[:180]
                        matches.append({
                            "platform": "Substack" if "substack" in feed_url else "Blog/Newsletter",
                            "publication": pub_name,
                            "title": i_title,
                            "url": i_link,
                            "date": i_date,
                            "snippet": clean_snippet,
                        })
        except Exception as e:
            log.debug("Error consultando feed transmedia %s: %s", feed_url, e)

    return len(matches), matches


SOURCES = [
    ("openalex", get_openalex_details),
    ("wikipedia", get_wikipedia_details),
    ("transmedia", get_transmedia_blog_details),
    ("altmetric", get_altmetric_details),
    ("hackernews", get_hackernews_details),
    ("stackexchange", get_stackexchange_details),
    ("crossref", get_crossref_details),
    ("wayback", get_wayback_details),
]


def init_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS doi_events(
            doi TEXT, source TEXT, count INTEGER, detail TEXT,
            checked_at TEXT, PRIMARY KEY(doi, source, checked_at))"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_doi_events_doi ON doi_events(doi, checked_at DESC)")
    conn.commit()
    return conn


def track_doi(raw_doi: str, db_path: str = DB_PATH, force_refresh: bool = False) -> dict:
    """
    Rastrea un DOI a traves de todas las fuentes abiertas y persiste el resultado.
    Si force_refresh es False y se consultó hace menos de 6 horas, devuelve la caché.
    """
    doi = clean_doi(raw_doi)
    if not doi:
        return {"error": "DOI inválido o vacío", "doi": raw_doi}

    conn = init_db(db_path)
    try:
        # Comprobar cache reciente (< 6 horas)
        if not force_refresh:
            rows = conn.execute(
                "SELECT source, count, detail, checked_at FROM doi_events WHERE doi = ? ORDER BY checked_at DESC",
                (doi,)
            ).fetchall()
            if rows:
                latest_time = rows[0]["checked_at"]
                try:
                    dt = datetime.fromisoformat(latest_time.replace("Z", "+00:00"))
                    diff_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
                    if diff_hours < 6.0:
                        # Reconstruir resumen desde DB
                        summary = {}
                        for r in rows:
                            src = r["source"]
                            if src not in summary:
                                try:
                                    det = json.loads(r["detail"])
                                except Exception:
                                    det = r["detail"]
                                summary[src] = {"count": r["count"], "detail": det}
                        return {
                            "doi": doi,
                            "cached": True,
                            "checked_at": latest_time,
                            "sources": summary,
                        }
                except Exception:
                    pass

        # Escaneo en vivo
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        summary = {}

        # 1. Obtener primero OpenAlex y Crossref para extraer el título canónico
        oa_count, oa_detail = get_openalex_details(doi)
        summary["openalex"] = {"count": oa_count, "detail": oa_detail}
        article_title = (oa_detail.get("title") if isinstance(oa_detail, dict) else "") or ""

        if not article_title:
            cr_count, cr_detail = get_crossref_details(doi)
            summary["crossref"] = {"count": cr_count, "detail": cr_detail}
            article_title = (cr_detail.get("title") if isinstance(cr_detail, dict) else "") or ""
        else:
            cr_count, cr_detail = get_crossref_details(doi)
            summary["crossref"] = {"count": cr_count, "detail": cr_detail}

        # 2. Consultar el resto de fuentes pasando el título para búsquedas exactas
        for name, fn in [
            ("wikipedia", lambda d: get_wikipedia_details(d)),
            ("transmedia", lambda d: get_transmedia_blog_details(d, article_title)),
            ("altmetric", lambda d: get_altmetric_details(d)),
            ("hackernews", lambda d: get_hackernews_details(d, article_title)),
            ("stackexchange", lambda d: get_stackexchange_details(d, article_title)),
            ("wayback", lambda d: get_wayback_details(d)),
        ]:
            try:
                count, detail = fn(doi)
            except Exception as e:
                count, detail = 0, {"error": str(e)[:100]}
            summary[name] = {"count": count, "detail": detail}

        # 3. Persistir en SQLite
        for name, data_item in summary.items():
            conn.execute(
                "INSERT OR REPLACE INTO doi_events(doi, source, count, detail, checked_at) VALUES (?, ?, ?, ?, ?)",
                (doi, name, data_item["count"], json.dumps(data_item["detail"], ensure_ascii=False), now)
            )

        conn.commit()
        return {
            "doi": doi,
            "cached": False,
            "checked_at": now,
            "sources": summary,
        }
    finally:
        conn.close()


def get_doi_history(raw_doi: str, db_path: str = DB_PATH) -> list[dict]:
    """Devuelve la serie temporal historica registrada para un DOI."""
    doi = clean_doi(raw_doi)
    if not doi:
        return []
    conn = init_db(db_path)
    try:
        rows = conn.execute(
            "SELECT source, count, detail, checked_at FROM doi_events WHERE doi = ? ORDER BY checked_at ASC",
            (doi,)
        ).fetchall()
        result = []
        for r in rows:
            try:
                det = json.loads(r["detail"])
            except Exception:
                det = r["detail"]
            result.append({
                "source": r["source"],
                "count": r["count"],
                "detail": det,
                "checked_at": r["checked_at"],
            })
        return result
    finally:
        conn.close()
