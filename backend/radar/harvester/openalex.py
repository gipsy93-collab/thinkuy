"""Harvester OpenAlex (api.openalex.org) — cobertura global, gratuita, sin API key.

Filtro por ISSN de las revistas del catálogo (print y online, con OR por pipe),
ventana de fechas y tipo article|review. Paginación por cursor (per-page=100).
Polite pool vía mailto=. Los abstracts vienen como inverted index y se reconstruyen.
"""
from __future__ import annotations

import logging
import time

from .. import config
from ..normalize import unescape
from .base import Article

log = logging.getLogger("radar.openalex")

BASE = "https://api.openalex.org/works"


def _abstract_from_inverted(inv: dict | None) -> str | None:
    """Reconstruye el abstract desde abstract_inverted_index (palabra -> posiciones)."""
    if not inv:
        return None
    pos: dict[int, str] = {}
    for word, idxs in inv.items():
        if isinstance(idxs, list):
            for i in idxs:
                pos[int(i)] = word
    if not pos:
        return None
    return unescape(" ".join(pos[i] for i in sorted(pos))).strip() or None


def parse_item(item: dict) -> Article | None:
    title = item.get("title") or item.get("display_name")
    if not title:
        return None
    doi = (item.get("doi") or "").strip().lower()
    if "doi.org/" in doi:
        doi = doi.rsplit("doi.org/", 1)[-1]
    doi = doi or None

    authors = []
    for au in item.get("authorships") or []:
        author = au.get("author") or {}
        name = author.get("display_name") or au.get("raw_author_name") or ""
        name = unescape(name).strip()
        if not name:
            continue
        if " " in name:
            given, family = name.rsplit(" ", 1)
        else:
            given, family = "", name
        orcid = (author.get("orcid") or "").replace("https://orcid.org/", "").strip() or None
        authors.append({"given": given, "family": family, "orcid": orcid})

    src = (item.get("primary_location") or {}).get("source") or {}
    journal = unescape(src.get("display_name") or "")
    issn = src.get("issn_l") or (src.get("issn") or [None])[0]

    biblio = item.get("biblio") or {}
    volume = biblio.get("volume") or None
    issue = biblio.get("issue") or None
    first = (biblio.get("first_page") or "").strip()
    last = (biblio.get("last_page") or "").strip()
    pages = f"{first}-{last}" if (first and last) else (first or None)

    oa = (item.get("open_access") or {}).get("is_oa")
    if oa is None:
        oa = (item.get("primary_location") or {}).get("is_oa")
    landing = (item.get("primary_location") or {}).get("landing_page_url")
    url = landing or (f"https://doi.org/{doi}" if doi else None)
    oaid = (item.get("id") or "").replace("https://openalex.org/", "").strip() or None
    refs = [
        (x or "").replace("https://openalex.org/", "").strip()
        for x in (item.get("referenced_works") or [])
        if x
    ]

    # Keywords ML de OpenAlex: descartar conceptos desambiguados (paréntesis) y de bajo score
    keywords = [
        k.get("display_name")
        for k in (item.get("keywords") or [])
        if k.get("display_name")
        and "(" not in k["display_name"]
        and (k.get("score") or 0) >= 0.5
    ][:10]

    return Article(
        title=unescape(title),
        title_alt=None,
        abstract=_abstract_from_inverted(item.get("abstract_inverted_index")),
        keywords=keywords,
        authors=authors,
        journal_title=journal or None,
        issn=issn,
        volume=str(volume) if volume else None,
        issue=str(issue) if issue else None,
        pages=pages,
        year=item.get("publication_year"),
        pub_date=item.get("publication_date"),
        lang=(item.get("language") or None),
        url=url,
        source="openalex",
        source_id=oaid or item.get("id"),
        doi=doi,
        access="oa" if oa else "closed",
        cited_by=item.get("cited_by_count"),
        openalex_id=oaid,
        referenced_ids=refs,
    )


def harvest_issns(http, issns: list[str], date_from: str,
                 max_articles: int = 150, delay: float | None = None) -> list[Article]:
    """Cosecha obras desde `date_from` para un lote de ISSN (OR por pipe)."""
    delay = delay if delay is not None else config.REQUEST_DELAY
    out: list[Article] = []
    if not issns:
        return out
    issn_filter = "|".join(issns)
    params = {
        "filter": f"primary_location.source.issn:{issn_filter},type:article|review,from_publication_date:{date_from}",
        "per-page": 100,
        "cursor": "*",
        "mailto": config.MAILTO,
    }
    cursor = "*"
    while len(out) < max_articles:
        params["cursor"] = cursor
        try:
            resp = http.get(BASE, params=params, timeout=45, headers=config.openalex_headers())
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.warning("OpenAlex lotes [%s…]: %s", issns[0], e)
            break
        results = data.get("results") or []
        for it in results:
            art = parse_item(it)
            if art:
                out.append(art)
            if len(out) >= max_articles:
                break
        nxt = data.get("meta", {}).get("next_cursor")
        if not nxt or nxt == cursor or not results:
            break
        cursor = nxt
        time.sleep(delay)
    return out