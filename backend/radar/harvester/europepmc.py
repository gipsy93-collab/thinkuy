"""Harvester Europe PMC (REST): búsqueda + textos completos OA de biomedicina/ciencia.

`search()` consulta el REST (query libre, p. ej. por ISSN o keywords) y devuelve
metadatos + `fulltext_url`. `fulltext_xml()` recupera el XML del texto completo
para los artículos OA (vía limpia y legal para almacenar texto).
"""
from __future__ import annotations

import logging
import time

import httpx

from .. import config
from ..normalize import year_of
from .base import Article

log = logging.getLogger("radar.europepmc")

REST = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def search(http: httpx.Client, query: str, limit: int = 100,
           date_from: str | None = None, delay: float | None = None) -> list[Article]:
    delay = delay if delay is not None else config.REQUEST_DELAY
    params = {"query": query, "format": "json", "pageSize": min(limit, 1000)}
    if date_from:
        params["dateRange"] = f"{date_from} TO *"
    out: list[Article] = []
    try:
        resp = http.get(f"{REST}/search", params=params, timeout=45)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning("Europe PMC query «%s»: %s", query[:60], e)
        return []
    for r in (data.get("resultList", {}).get("result") or []):
        doi = (r.get("doi") or "").strip().lower() or None
        year = year_of(r.get("firstPublicationDate"))
        ft = r.get("fullTextUrlList", {}).get("fullTextUrl") or []
        pdf_url = next((u.get("url") for u in ft if u.get("documentStyle") == "pdf" and u.get("availability") == "Open access"), None)
        authors = [{"family": (n.get("lastName") or ""), "given": (n.get("firstName") or "")}
                   for n in (r.get("authorList", {}).get("author") or [])]
        authors = [a for a in authors if a["family"] or a["given"]]
        out.append(Article(
            title=(r.get("title") or "").strip(),
            doi=doi,
            abstract=(r.get("abstractText") or "").strip() or None,
            keywords=[k.get("keyword") for k in (r.get("keywordList", {}).get("keyword") or [])][:10],
            authors=authors,
            journal_title=r.get("journalInfo", {}).get("journal", {}).get("title"),
            year=year,
            pub_date=(r.get("firstPublicationDate") or "")[:10] or None,
            lang="es",
            url=f"https://europepmc.org/article/{r.get('source')}/{r.get('id')}" if r.get("id") else None,
            source="europepmc",
            source_id=r.get("pmcid") or r.get("id") or None,
            access="oa" if r.get("isOpenAccess") == "Y" else "closed",
            cited_by=r.get("citedByCount") or 0,
            pdf_url=pdf_url,
        ))
    time.sleep(delay)
    log.info("Europe PMC «%s»: %d results", query[:40], len(out))
    return out


def fulltext_xml(http: httpx.Client, source: str, id_: str) -> str | None:
    """Texto completo en XML de un artículo OA (source: 'PMC' o 'MED')."""
    try:
        resp = http.get(f"{REST}/{source}/{id_}/fullTextXML", timeout=45)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        log.warning("Europe PMC fulltext %s/%s: %s", source, id_, e)
    return None