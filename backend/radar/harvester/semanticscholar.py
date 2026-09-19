"""Harvester Semantic Scholar (Graph API): citas, referencias y abstracts.

Enriquece artículos del catálogo con `cited_by` (citationCount de S2), referencias y
abstracts, mediante el endpoint por DOI y el de lote (batch). Sin API key el límite es
~100 req/5 min (S2_THROTTLE); con S2_API_KEY sube a ~1.000.
"""
from __future__ import annotations

import logging
import os
import time

import httpx

log = logging.getLogger("radar.semanticscholar")

GRAPH = "https://api.semanticscholar.org/graph/v1"
FIELDS = "paperId,title,abstract,citationCount,referenceCount,externalIds,authors,references.paperId,references.externalIds"

S2_API_KEY = os.environ.get("S2_API_KEY", "")
S2_THROTTLE = 3.5 if not S2_API_KEY else 1.1


def _headers() -> dict:
    return {"x-api-key": S2_API_KEY} if S2_API_KEY else {}


def paper_by_doi(http: httpx.Client, doi: str) -> dict | None:
    try:
        resp = http.get(f"{GRAPH}/paper/DOI:{doi}", params={"fields": FIELDS},
                        headers=_headers(), timeout=30)
    except Exception as e:
        log.warning("S2 %s: %s", doi, e)
        return None
    time.sleep(S2_THROTTLE)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        log.warning("S2 %s: HTTP %s", doi, resp.status_code)
        return None
    return resp.json()


def _normalize(p: dict) -> dict | None:
    if not p or not p.get("title"):
        return None
    refs = []
    for r in (p.get("references") or []):
        doi = ((r.get("externalIds") or {}).get("DOI") or "").strip().lower()
        if doi:
            refs.append(doi)
        elif r.get("paperId"):
            refs.append(r["paperId"].upper())
    return {
        "s2_paper_id": p.get("paperId"),
        "s2_cited_by": p.get("citationCount") or 0,
        "s2_reference_count": p.get("referenceCount") or 0,
        "s2_abstract": p.get("abstract"),
        "s2_references": refs,
    }


def paper_batch(http: httpx.Client, dois: list[str]) -> list[dict]:
    """Lote de hasta 500 DOIs. Devuelve lista de dicts normalizados (mismo orden)."""
    if not dois:
        return []
    out: list[dict] = []
    for i in range(0, len(dois), 100):
        chunk = dois[i:i + 100]
        try:
            resp = http.post(f"{GRAPH}/paper/batch",
                             params={"fields": FIELDS},
                             json={"ids": [f"DOI:{d}" for d in chunk]},
                             headers={**_headers(), "Content-Type": "application/json"},
                             timeout=60)
            time.sleep(S2_THROTTLE)
            if resp.status_code != 200:
                log.warning("S2 batch HTTP %s", resp.status_code)
                out.extend([None] * len(chunk))
                continue
            items = resp.json() or []
            out.extend(_normalize(p) if isinstance(p, dict) else None for p in items)
        except Exception as e:
            log.warning("S2 batch: %s", e)
            out.extend([None] * len(chunk))
    return out


def enrich_articles(http: httpx.Client, articles: list[dict], limit: int | None = None) -> dict:
    """Enriquece artículos con DOI: cited_by y referencias de S2."""
    targets = [a for a in articles if (a.get("doi") or "").strip()]
    if limit:
        targets = targets[:limit]
    norms = paper_batch(http, [(a.get("doi") or "").strip().lower() for a in targets])
    enriched = 0
    for a, n in zip(targets, norms):
        if not n:
            continue
        enriched += 1
        yield {**a, **n}
    log.info("Semantic Scholar: %d enriquecidos de %d", enriched, len(targets))