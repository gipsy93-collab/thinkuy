"""Auto-ingesta de obras citadas ausentes del catálogo.

Dado un DOI citado (p. ej. desde la lista de referencias de un PDF), lo resuelve
en OpenAlex y lo ingiere con `upsert` si tiene DOI válido. Deduplica contra el
catálogo y registra la cosecha. Límite de cortesía por llamada.
"""
from __future__ import annotations

import logging
import time

import httpx

from .. import config, db
from ..citation_graph import clean_doi
from . import openalex

log = logging.getLogger("radar.cited")

MAX_PER_CALL = 20


def _fetch_openalex_work(http: httpx.Client, doi: str) -> dict | None:
    try:
        resp = http.get(
            f"{openalex.BASE}/https://doi.org/{doi}",
            params={"mailto": config.MAILTO},
            headers=config.openalex_headers(),
            timeout=30,
        )
    except Exception as e:
        log.warning("OpenAlex %s: %s", doi, e)
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def ensure_cited_articles(conn, http: httpx.Client | None, dois: list[str],
                          max_new: int = MAX_PER_CALL) -> list[str]:
    """Ingiere los DOIs citados que falten en el catálogo. Devuelve los ingeridos."""
    clean = []
    seen = set()
    for d in dois or []:
        c = clean_doi(d)
        if c and c not in seen:
            seen.add(c)
            clean.append(c)
    if not clean:
        return []

    existing = {
        (r["doi"] or "").strip().lower()
        for r in conn.execute("SELECT doi FROM articles WHERE doi IS NOT NULL").fetchall()
    }
    missing = [d for d in clean if d not in existing][:max_new]
    if not missing:
        return []

    close_http = http is None
    client = http or httpx.Client(
        headers={"User-Agent": config.USER_AGENT}, follow_redirects=True, timeout=30.0
    )
    ingested: list[str] = []
    try:
        for doi in missing:
            item = _fetch_openalex_work(client, doi)
            if not item:
                continue
            art = openalex.parse_item(item)
            if not art or not (art.doi or "").strip():
                continue
            try:
                status, _ = db.upsert_article(conn, art.db_row())
                if status == "new":
                    ingested.append(doi)
            except Exception as e:
                log.warning("upsert %s: %s", doi, e)
            time.sleep(0.4)
    finally:
        if close_http:
            client.close()
    if ingested:
        try:
            db.log_harvest(conn, "cited_auto", "ok", len(ingested), len(ingested),
                           f"desde referencias ({len(missing)} consultados)")
        except Exception:
            pass
    return ingested
