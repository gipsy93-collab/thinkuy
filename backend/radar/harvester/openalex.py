"""Harvester OpenAlex (api.openalex.org) — cobertura global, gratuita, sin API key.

Filtro por ISSN de las revistas del catálogo (print y online, con OR por pipe),
ventana de fechas y tipo article|review. Paginación por cursor (per-page=100).
Polite pool vía mailto=. Los abstracts vienen como inverted index y se reconstruyen.
"""
from __future__ import annotations

import logging
import time

from .. import config
from ..normalize import clean_doi, unescape
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


def get_works_by_dois(http, dois: list[str], per_page: int = 50, timeout: float = 20.0) -> list[dict]:
    """Obras crudas por lote de DOIs (`doi:d1|d2|...`), en trozos de 50."""
    limpios = [clean_doi(d) for d in (dois or []) if d]
    limpios = [d for d in limpios if d]
    out: list[dict] = []
    for i in range(0, len(limpios), per_page):
        chunk = limpios[i:i + per_page]
        try:
            r = http.get(BASE, params={"filter": "doi:" + "|".join(chunk),
                                       "per-page": per_page, "mailto": config.MAILTO},
                         headers=config.openalex_headers(), timeout=timeout)
            if r.status_code == 200:
                out.extend(r.json().get("results") or [])
        except Exception as e:
            log.warning("OpenAlex lote de DOIs: %s", e)
        time.sleep(config.REQUEST_DELAY)
    return out


def get_work_by_doi(http, doi: str, timeout: float = 10.0) -> dict | None:
    """Obra cruda de OpenAlex por DOI (o None)."""
    doi = (doi or "").strip().lower()
    if not doi:
        return None
    try:
        r = http.get(f"{BASE}/https://doi.org/{doi}", params={"mailto": config.MAILTO},
                     headers=config.openalex_headers(), timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("OpenAlex work %s: %s", doi, e)
    return None


def get_works_by_ids(http, ids: list[str], per_page: int = 50, timeout: float = 20.0) -> list[dict]:
    """Obras crudas por lote de IDs OpenAlex (`W...`), en trozos de 50."""
    limpios = [str(i).replace("https://openalex.org/", "").strip() for i in (ids or []) if i]
    out: list[dict] = []
    for i in range(0, len(limpios), per_page):
        chunk = limpios[i:i + per_page]
        try:
            r = http.get(BASE, params={"filter": "openalex_id:" + "|".join(chunk),
                                       "per-page": per_page, "mailto": config.MAILTO},
                         headers=config.openalex_headers(), timeout=timeout)
            if r.status_code == 200:
                out.extend(r.json().get("results") or [])
        except Exception as e:
            log.warning("OpenAlex lote de ids: %s", e)
        time.sleep(config.REQUEST_DELAY)
    return out


def get_citing_works(http, openalex_id: str, limit: int = 25, timeout: float = 20.0) -> list[dict]:
    """Obras crudas que citan a la dada (por id OpenAlex `W...`)."""
    oid = str(openalex_id or "").replace("https://openalex.org/", "").strip()
    if not oid:
        return []
    try:
        r = http.get(BASE, params={"filter": f"cites:{oid}", "per-page": min(max(limit, 1), 100),
                                   "sort": "cited_by_count:desc", "mailto": config.MAILTO},
                     headers=config.openalex_headers(), timeout=timeout)
        if r.status_code == 200:
            return r.json().get("results") or []
    except Exception as e:
        log.warning("OpenAlex citantes de %s: %s", oid, e)
    return []


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