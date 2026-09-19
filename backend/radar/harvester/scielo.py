"""Harvester SciELO vía Article Meta API (articlemeta.scielo.org).

Endpoints verificados en vivo:
  GET /api/v1/journal/?collection=scl&limit=100&offset=N   -> revistas de la colección
  GET /api/v1/article/identifiers/?collection=X&issn=Y&from=&to=&limit=100&offset=N
  GET /api/v1/article/?collection=X&code=S...&format=xml   -> registro completo

Mapeo de campos empírico (formato=xml):
  v10 autores [{k: ORCID, n: nombres, s: apellido}], v12 títulos [{l: idioma, _: texto}],
  v30 revista abreviada, v31 volumen, v32 número, v35 ISSN impreso,
  v38 tipo (GRA = research article), v40 idioma principal, v62 editorial,
  v65 año '2025xxxx', v71 acceso ('oa' = open access), v83 abstracts [{a: idioma}],
  v85 keywords [{k: keyword, l: idioma}], v91 fecha de procesado, v100 revista,
  v237 DOI, v435 ISSNs, v440 áreas temáticas (revistas), v441 WoS área (revistas),
  v854 WoS subject (revistas), v880 código. El parámetro issn= filtra por cualquiera
  de los ISSN de la revista.
"""
from __future__ import annotations

import logging
import re
import time

from .. import config, profile
from ..normalize import am_date, unescape, year_of, norm
from .base import Article

log = logging.getLogger("radar.scielo")

API = "https://articlemeta.scielo.org/api/v1"

# Colecciones iberoamericanas del perfil de campo activo
COLLECTIONS = list(profile.field_profile.collections or [])

# Términos del perfil para considerar una revista como del campo (v440/v441/v854/título)
COMM_TERMS = list(profile.field_profile.discovery_terms or [])


def _clean(s: str) -> str:
    return norm(s)


_ISSN_RE = re.compile(r"^\d{4}-\d{3}[\dXx]$")


def _valid_issns(values: list[str]) -> list[str]:
    """Filtra solo ISSN reales (evita 'ONLIN'/'PRINT' que aparecen en campos v35 de revistas)."""
    return [v.strip().upper() for v in values if _ISSN_RE.match(v.strip())]


def _text_list(v) -> list[str]:
    """Convierte un valor vNNN de la API (lista de dicts/str) en lista de strings."""
    if not v:
        return []
    out = []
    for item in v:
        if isinstance(item, dict):
            out.append(str(item.get("_") or "").strip())
        elif isinstance(item, str):
            out.append(item.strip())
    return [x for x in out if x]


def _flag(v, *flags) -> bool:
    vals = [str(i.get("_") or "") for i in v] if isinstance(v, list) else [str(v or "")]
    return any(any(f.upper() in x.upper() for f in flags) for x in vals)


def _http_get(http, path: str, params: dict) -> dict:
    url = f"{API}{path}"
    resp = http.get(url, params=params, timeout=45)
    resp.raise_for_status()
    return resp.json()


def discover_journals(http, collections: list[str] | None = None, max_per_collection: int = 400) -> list[dict]:
    """Auto-descubre revistas de las colecciones SciELO, filtradas por el campo si lo hay."""
    collections = collections or COLLECTIONS
    found: list[dict] = []
    for coll in collections:
        offset = 0
        while offset < max_per_collection:
            try:
                data = _http_get(http, "/journal/", {"collection": coll, "limit": 100, "offset": offset})
            except Exception as e:
                log.warning("Cosecha de revistas %s falló: %s", coll, e)
                break
            if not isinstance(data, list) or not data:
                break
            for j in data:
                if not isinstance(j, dict):
                    continue
                title = _text_list(j.get("v100"))[:1]
                title = title[0] if title else None
                if not title:
                    continue
                subjects = " ".join(
                    t
                    for k in ("v440", "v441", "v854")
                    for t in _text_list(j.get(k))
                )
            hay = _clean(f"{title} {subjects}")
            # La revista es del campo si coincide algún término en área o título.
            # Con perfil NEUTRO no hay términos de disciplina: no se filtra por campo, porque
            # el alcance ya lo define la colección iberoamericana. Antes, una lista vacía hacía
            # que `any(...)` fuera falso y se descartara TODAS las revistas.
            if COMM_TERMS and not any(_clean(t) in hay for t in COMM_TERMS):
                continue
                # ISSN reales (los registros de revista ponen 'ONLIN'/'PRINT' en v35;
                # los ISSN legítimos están en 'issns' / v400)
                issns = _valid_issns(_text_list(j.get("issns")) or _text_list(j.get("v400")))
                if not issns:
                    continue
                found.append({
                    "title": unescape(title),
                    "issn_print": issns[0],
                    "issn_online": issns[1] if len(issns) > 1 else None,
                    "country": None,
                    "source": "scielo",
                    "collection": coll,
                    "subject_areas": _text_list(j.get("v440")),
                    "auto_discovered": True,
                })
                log.debug("Revista SciELO %s [%s]: %s", coll, issns, title)
            if len(data) < 100:
                break
            offset += 100
        time.sleep(config.REQUEST_DELAY)
    return found


def parse_article(raw: dict) -> Article | None:
    """Convierte el JSON de /article/?format=xml en un Article Radar."""
    art = raw.get("article") or raw
    if not isinstance(art, dict):
        return None
    # Solo artículos de investigación (GRA) según v38
    if not _flag(art.get("v38"), "GRA"):
        return None

    lang_main = _text_list(art.get("v40"))[:1]
    lang_main = lang_main[0] if lang_main else "es"

    titles = art.get("v12") or []
    title, title_alt = None, None
    best = None
    for t in titles:
        if isinstance(t, dict):
            lang = t.get("l") or ""
            text = unescape(t.get("_") or "")
            if not text:
                continue
            rank = {"es": 2, "pt": 3}.get(lang, 1)
            if lang == lang_main:
                rank = 4
            if best is None or rank > best[0]:
                best = (rank, text)
    if best:
        title = best[1]
    if not title:
        return None

    authors = []
    for au in art.get("v10") or []:
        if isinstance(au, dict):
            given = unescape(au.get("n") or "")
            family = unescape(au.get("s") or "")
            orcid = (au.get("k") or "").strip()
            if family or given:
                authors.append({"given": given, "family": family, "orcid": orcid or None})

    keywords = []
    seen_kw = set()
    for kw in art.get("v85") or []:
        if isinstance(kw, dict):
            k = unescape(kw.get("k") or "").strip()
            if k and k.lower() not in seen_kw:
                seen_kw.add(k.lower())
                keywords.append(k)

    abstracts = art.get("v83") or []
    abstract = None
    best_ab = None
    for ab in abstracts:
        if isinstance(ab, dict):
            lang = (ab.get("l") or "").strip().lower()
            text = unescape(ab.get("a") or ab.get("_") or "").strip()
            if not text:
                continue
            text = re.sub(r"^(?:resumen|resumo|abstract)\s*[:\-–—]?\s*", "", text, flags=re.IGNORECASE).strip()
            rank = {"es": 2, "pt": 3}.get(lang, 1)
            if lang == lang_main:
                rank = 4
            if best_ab is None or rank > best_ab[0]:
                best_ab = (rank, text)
    if best_ab:
        abstract = best_ab[1]

    journal = _text_list(art.get("v100")) or _text_list(art.get("v30"))
    issns = _text_list(art.get("v435")) or _text_list(art.get("v35"))
    doi = _text_list(art.get("v237"))[:1]
    doi = doi[0].strip().lower() if doi else None
    year_raw = _text_list(art.get("v65"))[:1]
    year = year_of(year_raw[0]) if year_raw else None
    pub_date = am_date(_text_list(art.get("v91"))[:1][0]) if _text_list(art.get("v91")) else None
    code = str(art.get("code") or raw.get("code") or "")
    coll = str(art.get("collection") or raw.get("collection") or "")

    url = f"https://doi.org/{doi}" if doi else None
    access = "oa" if _flag(art.get("v71"), "oa") else "closed"

    return Article(
        title=unescape(title),
        title_alt=unescape(title_alt) if title_alt else None,
        abstract=abstract,
        keywords=keywords,
        authors=authors,
        journal_title=unescape(journal[0]) if journal else None,
        issn=issns[0] if issns else None,
        volume=_text_list(art.get("v31"))[:1][0] if _text_list(art.get("v31")) else None,
        issue=_text_list(art.get("v32"))[:1][0] if _text_list(art.get("v32")) else None,
        pages=None,
        year=year,
        pub_date=pub_date,
        lang=lang_main,
        url=url,
        source="scielo",
        source_id=code,
        doi=doi,
        access=access,
    )


def harvest_journal(http, collection: str, issn: str, date_from: str, date_to: str,
                    max_articles: int = 60, delay: float | None = None) -> list[Article]:
    """Cosecha artículos recientes de una revista SciELO (por su ISSN)."""
    delay = delay if delay is not None else config.REQUEST_DELAY
    out: list[Article] = []
    offset = 0
    while len(out) < max_articles:
        try:
            data = _http_get(http, "/article/identifiers/", {
                "collection": collection, "issn": issn,
                "from": date_from, "to": date_to,
                "limit": 50, "offset": offset,
            })
        except Exception as e:
            log.warning("identifiers %s/%s falló: %s", collection, issn, e)
            break
        objs = data.get("objects") or []
        for o in objs:
            if len(out) >= max_articles:
                break
            code = o.get("code")
            if not code:
                continue
            try:
                raw = _http_get(http, "/article/", {
                    "collection": o.get("collection", collection),
                    "code": code, "format": "xml",
                })
            except Exception as e:
                log.warning("artículo %s falló: %s", code, e)
                continue
            art = parse_article(raw)
            if art:
                out.append(art)
            time.sleep(delay)
        total = data.get("meta", {}).get("total", 0)
        if offset + 50 >= total or not objs:
            break
        offset += 50
    return out