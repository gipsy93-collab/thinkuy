"""Harvester Unpaywall: localiza el acceso abierto legal de un artículo por DOI.

Enriquece cada artículo con su estado OA real (gold/green/hybrid/bronze), el tipo de
host y la URL del mejor PDF abierto. Unpaywall exige un `email` (polite pool).
Regla legal: solo se guardan URLs de PDFs con licencia abierta; nunca se descargan PDFs.
"""
from __future__ import annotations

import logging
import time

import httpx

from .. import config

log = logging.getLogger("radar.unpaywall")

API = "https://api.unpaywall.org/v2"


def enrich_doi(http: httpx.Client, doi: str, email: str | None = None,
               delay: float | None = None) -> dict | None:
    """Consulta Unpaywall para un DOI. Devuelve dict normalizado o None si no hay OA."""
    email = email or config.MAILTO
    delay = delay if delay is not None else config.REQUEST_DELAY
    try:
        resp = http.get(f"{API}/{doi}", params={"email": email}, timeout=30)
    except Exception as e:
        log.warning("Unpaywall %s: %s", doi, e)
        return None
    time.sleep(delay)
    if resp.status_code != 200:
        return None
    data = resp.json()
    best = data.get("best_oa_location") or {}
    return {
        "is_oa": bool(data.get("is_oa")),
        "oa_status": data.get("oa_status"),
        "host_type": best.get("host_type"),
        "pdf_url": (best.get("url_for_pdf") or best.get("url")),
        "updated": data.get("updated"),
    }


def enrich_articles(http: httpx.Client, articles: list[dict], limit: int | None = None) -> dict:
    """Enriquece una lista de artículos (los que tengan DOI y aún no tengan pdf_url)."""
    done = skipped = 0
    for a in articles[:limit]:
        doi = (a.get("doi") or "").strip().lower()
        if not doi or a.get("pdf_url"):
            skipped += 1
            continue
        info = enrich_doi(http, doi)
        if info and info.get("is_oa"):
            done += 1
            yield {**a, **info}
    log.info("Unpaywall: %d enriquecidos, %d omitidos", done, skipped)