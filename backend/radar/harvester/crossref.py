"""Harvester Crossref (api.crossref.org) — cobertura amplia y metadatos ricos.

Uso: filtra por ISSN de las revistas registradas en el catálogo Radar (impreso y
online), con cursor para paginar. El parámetro mailto= mantiene el trato
preferente del "polite pool". Los abstracts vienen en JATS y se limpian.
"""
from __future__ import annotations

import logging
import re
import time

from .. import config
from ..normalize import unescape
from .base import Article

log = logging.getLogger("radar.crossref")

BASE = "https://api.crossref.org/works"
_TAG_RE = re.compile(r"<[^>]+>")


def _jats_text(s: str | None) -> str | None:
    if not s:
        return None
    s = re.sub(r"<jats:p>|</jats:p>|<jats:title>|</jats:title>", " ", s)
    s = _TAG_RE.sub(" ", s)
    return unescape(s).strip() or None


def _first(v):
    if isinstance(v, list) and v:
        return v[0]
    return v


def parse_item(item: dict) -> Article | None:
    title = _first(item.get("title"))
    if not title:
        return None
    journal = _first(item.get("container-title"))
    doi = (item.get("DOI") or "").strip().lower()
    authors = []
    for au in item.get("author") or []:
        given = au.get("given", "")
        family = au.get("family", "")
        orcid = au.get("ORCID", "") or None
        if family or given:
            authors.append({"given": given, "family": family, "orcid": orcid})
    issued = item.get("issued", {}).get("date-parts") or [[]]
    parts = issued[0]
    year = parts[0] if parts and len(parts) > 0 else None
    pub_date = None
    if len(parts) >= 3 and parts[0] and parts[1] and parts[2]:
        pub_date = f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
    elif len(parts) >= 1 and parts[0]:
        pub_date = f"{parts[0]:04d}-01-01"
    keywords = []
    subjects = [str(s) for s in (item.get("subject") or [])]
    for s in subjects:
        if len(s) < 80:
            keywords.append(s)
    lang = (item.get("language") or "").strip() or None
    if lang and "-" in lang:
        lang = lang.split("-")[0]
    return Article(
        title=unescape(title),
        title_alt=None,
        abstract=_jats_text(item.get("abstract")),
        keywords=keywords,
        authors=authors,
        journal_title=unescape(journal) if journal else None,
        issn=_first(item.get("ISSN")) if item.get("ISSN") else None,
        volume=str(item.get("volume")) if item.get("volume") else None,
        issue=str(item.get("issue")) if item.get("issue") else None,
        pages=str(item.get("page")) if item.get("page") else None,
        year=int(year) if year else None,
        pub_date=pub_date,
        lang=lang,
        url=(item.get("URL") or (f"https://doi.org/{doi}" if doi else None)),
        source="crossref",
        source_id=doi,
        doi=doi,
        access="oa" if (item.get("license") or []) else "unknown",
        cited_by=item.get("is-referenced-by-count"),
    )


def harvest_by_issn(http, issn: str, date_from: str,
                    rows: int = 100, max_articles: int = 200,
                    delay: float | None = None) -> list[Article]:
    """Cosecha artículos de un ISSN desde `date_from` (YYYY-MM-DD)."""
    delay = delay if delay is not None else config.REQUEST_DELAY
    out: list[Article] = []
    cursor = "*"
    deadline = max_articles
    while len(out) < deadline:
        params = {
            "filter": f"issn:{issn},type:journal-article,from-pub-date:{date_from}",
            "rows": rows,
            "cursor": cursor,
            "select": "DOI,title,author,container-title,issued,volume,issue,page,abstract,URL,ISSN,subject,license,is-referenced-by-count",
            "mailto": config.MAILTO,
        }
        try:
            resp = http.get(BASE, params=params, timeout=45)
            resp.raise_for_status()
            data = resp.json()["message"]
        except Exception as e:
            log.warning("Crossref %s falló: %s", issn, e)
            break
        items = data.get("items") or []
        for it in items:
            art = parse_item(it)
            if art and art.doi:
                out.append(art)
            if len(out) >= deadline:
                break
        nxt = data.get("next-cursor")
        if not nxt or nxt == cursor or not items:
            break
        cursor = nxt
        time.sleep(delay)
    return out