"""Harvester CORE (api.core.ac.uk v3): búsqueda por keywords en ~360M agregados.

Requiere `CORE_API_KEY` en el entorno. Si no hay key, la fuente se reporta como
`no_key` (no falla el pipeline). Devuelve works con DOI/título/abstract/url.
"""
from __future__ import annotations

import logging
import os
import time

import httpx

from .. import config
from ..normalize import year_of
from .base import Article

log = logging.getLogger("radar.core")

API = "https://api.core.ac.uk/v3/search/works"
CORE_API_KEY = os.environ.get("CORE_API_KEY", "")


def available() -> bool:
    return bool(CORE_API_KEY)


def search(http: httpx.Client, query: str, limit: int = 50,
           date_from: str | None = None, delay: float | None = None) -> list[Article]:
    """Búsqueda por query CORE. Devuelve lista de Article."""
    if not available():
        log.warning("CORE sin API key (CORE_API_KEY). Fuente omitida.")
        return []
    delay = delay if delay is not None else config.REQUEST_DELAY
    params = {"q": query, "limit": min(limit, 100)}
    headers = {"Authorization": f"Bearer {CORE_API_KEY}", "Accept": "application/json"}
    out: list[Article] = []
    try:
        resp = http.get(API, params=params, headers=headers, timeout=45)
        time.sleep(delay)
        if resp.status_code == 401:
            log.warning("CORE: API key inválida")
            return []
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning("CORE query «%s»: %s", query[:60], e)
        return []

    for w in (data.get("results") or []):
        doi = (w.get("doi") or "").strip().lower()
        year = year_of(w.get("yearPublished") or w.get("publishedDate"))
        pub_date = (w.get("publishedDate") or "")[:10] or None
        if date_from and pub_date and pub_date < date_from:
            continue
        authors = []
        for au in (w.get("authors") or []):
            parts = (au.get("name") or "").strip().split()
            if parts:
                authors.append({"family": parts[-1], "given": " ".join(parts[:-1])})
        out.append(Article(
            title=(w.get("title") or "").strip(),
            doi=doi or None,
            abstract=(w.get("abstract") or "").strip() or None,
            keywords=[k.get("name") or k for k in (w.get("subjects") or [])][:10],
            authors=authors,
            journal_title=w.get("journalName") or (w.get("publisher") or ""),
            year=year,
            pub_date=pub_date,
            lang="es",
            url=w.get("downloadUrl") or w.get("url") or None,
            source="core",
            source_id=str(w.get("id") or ""),
            access="oa",
            cited_by=w.get("citationCount") or 0,
        ))
    log.info("CORE «%s»: %d works", query[:40], len(out))
    return out