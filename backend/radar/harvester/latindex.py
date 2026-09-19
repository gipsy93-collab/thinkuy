"""Latindex Catálogo 2.0 + Descubridor de Artículos.

Solo trabaja con el Catálogo 2.0 (idMod=1), nunca con el Directorio (idMod=0)
ni con Revistas en línea (idMod=2). El Catálogo 2.0 agrupa revistas en línea
que cumplen las 38 características de calidad editorial de Latindex (mín. 30/38).

Dos servicios integrados:
1) Catálogo de revistas (descubrimiento): exportación nativa JSON/CSV/XML:
   https://www.latindex.org/latindex/exportar/indiceRegion/json/{region}/{pais}/{idMod}
   - region=94 → Iberoamérica (4.051 revistas Cat 2.0 vigentes)
   - pais=10   → Colombia (171), etc.
   - idMod=1   → Catálogo 2.0 (solo en línea, calificadas)
2) Descubridor de Artículos (cosecha): búsqueda Solr sobre documentos a texto
   completo publicados en revistas del Catálogo 2.0:
   https://www.latindex.org/latindex/Solr/Busqueda?buscar=...&idModBus=3
   Paginación con `page=N` y `page-size=200` (verificado). Cada ítem trae año,
   ISSN, título+URL OJS, autores, revista, editorial, DOI y resumen.

Filosofía: igual que el resto de Thinkuy — el catálogo manda. Latindex aporta
REVISTAS (título, ISSN, país, editorial, subtemas) y ARTÍCULOS de esas revistas
certificadas (calidad contrastada); los artículos se complementan después con
Crossref/OpenAlex por ISSN y por DOI.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

import httpx

from .. import config, db
from .. import profile
from ..normalize import norm, unescape
from .base import Article

log = logging.getLogger("radar.latindex")

# Región Iberoamérica (Catálogo 2.0). region/pais siguen el formulario Latindex.
CATALOGO_IDMOD = 1
REGION_IBEROAMERICA = 94
EXPORT_URL = (
    "https://www.latindex.org/latindex/exportar/indiceRegion/json/"
    "{region}/{pais}/{idmod}"
)
ARTICLE_SEARCH_URL = "https://www.latindex.org/latindex/Solr/Busqueda"
ARTICLE_EXPORT_URL = "https://www.latindex.org/latindex/exportar/busquedaGeneral/json"

CACHE_TTL_DAYS = 7
ARTICLE_PAGE_SIZE = 200

_ISSN_RE = re.compile(r"^\d{4}-\d{3}[\dX]$")
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


# ---------------------------------------------------------------- fetch + caché

def _cache_path() -> Path:
    return config.DATA_DIR / "latindex" / "catalogo2_iberoamerica.json"


def _fetch_catalog(http: httpx.Client, region: int, pais: int,
                   use_cache: bool = True) -> list[dict]:
    """Descarga el catálogo JSON (con caché en data/latindex)."""
    cache = _cache_path()
    if use_cache and cache.exists():
        age_days = (date.today() - date.fromtimestamp(cache.stat().st_mtime)).days
        if age_days <= CACHE_TTL_DAYS:
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    log.info("Latindex desde caché: %d revistas", len(data))
                    return data
            except (OSError, json.JSONDecodeError):
                pass

    url = EXPORT_URL.format(region=region, pais=pais, idmod=CATALOGO_IDMOD)
    log.info("Descargando Catálogo 2.0 Latindex: %s", url)
    resp = http.get(url)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"Latindex no devolvió una lista: {type(data)}")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    log.info("Catálogo 2.0 Latindex: %d revistas (caché en %s)", len(data), cache)
    return data


# ---------------------------------------------------------------- filtro de campo

def _terms(profile) -> set[str]:
    """Términos del campo para decidir si una revista le pertenece."""
    terms = set()
    for t in (profile.discovery_terms or []):
        terms.add(norm(t))
    for f in (profile.topics or []):
        for kw in (f.get("keywords_es") or []) + (f.get("keywords_pt") or []):
            terms.add(norm(kw))
    for ax in (profile.editorial_axes or []):
        terms.add(norm(ax))
    return {t for t in terms if t}


def _journal_text(record: dict) -> str:
    """Texto normalizado (título + subtemas) de un registro Latindex."""
    title = norm(record.get("tit_propio") or "")
    subtemas = []
    for s in (record.get("subtemas") or []):
        n = norm(s.get("nom_subtema") or "")
        if n:
            subtemas.append(n)
    return " ".join([title] + subtemas)


def relevant(record: dict, terms: set[str]) -> bool:
    """¿La revista del Catálogo 2.0 pertenece al campo activo?"""
    if not terms:
        return True
    text = _journal_text(record)
    for t in terms:
        if t in text:
            return True
    return False


def _clean_issn(value: str | None) -> str | None:
    v = (value or "").strip().upper()
    return v if _ISSN_RE.match(v) else None


def to_journal(record: dict) -> dict:
    """Normaliza un registro Latindex al esquema de revistas de Thinkuy."""
    issn_online = _clean_issn(record.get("issn_e"))
    issn_print = _clean_issn(record.get("issn_imp")) or issn_online
    subtemas = [
        (s.get("nom_subtema") or "").strip()
        for s in (record.get("subtemas") or [])
        if (s.get("nom_subtema") or "").strip()
    ]
    return {
        "title": (record.get("tit_propio") or "").strip() or None,
        "issn_print": issn_print,
        "issn_online": issn_online,
        "country": (record.get("nombre_largo") or "").strip() or None,
        "publisher": (record.get("nombre_edi") or "").strip() or None,
        "subject_areas": subtemas,
        "source": "latindex",
        "auto_discovered": True,
        "latindex_id": record.get("folio_u"),
        "latindex_catalog_id": record.get("id_catalogo"),
    }


def discover_journals(http: httpx.Client, use_cache: bool = True) -> list[dict]:
    """Descubre revistas del campo activo en el Catálogo 2.0 (Iberoamérica)."""
    records = _fetch_catalog(http, REGION_IBEROAMERICA, 0, use_cache=use_cache)
    terms = _terms(profile.field_profile)
    selected = [to_journal(r) for r in records if relevant(r, terms)]

    # Dedupe por ISSN (online preferido, después impreso)
    seen: dict[str, dict] = {}
    for j in selected:
        key = j["issn_online"] or j["issn_print"] or (j["title"] or "").upper()
        if not key:
            continue
        seen.setdefault(key, j)
    out = list(seen.values())
    log.info("Catálogo 2.0: %d relevantes al campo (de %d)", len(out), len(records))
    return out


def seed_snapshot() -> list[dict]:
    """Devuelve la lista deduplicada de revistas del campo (sin red)."""
    import httpx as _h
    with _h.Client(headers={"User-Agent": config.USER_AGENT},
                   follow_redirects=True, timeout=45.0) as c:
        return discover_journals(c)


# ================================================================ Descubridor
# Búsqueda de artículos del Catálogo 2.0 (idModBus=3). El export JSON está
# protegido por el servidor (403 sin sesión fiable); usamos las páginas HTML
# paginadas, que sí responden, con page-size=200.

_ITEM_SPLIT = re.compile(r'(?=<div class="found-item">)')
_RE_YEAR = re.compile(r"A[ñn]o:</span>\s*<span>(\d{4})</span>")
_RE_ISSN = re.compile(r"ISSN:\s*</span>\s*<span>([^<]+)</span>")
_RE_TITLE = re.compile(r'<a href="([^"]+)"[^>]*>\s*<strong>(.*?)</strong>', re.S)
_RE_AUTHORS = re.compile(r"</a><br>\s*</div>\s*<div class=\"pb-2\">\s*(.*?)<br>", re.S)
_RE_JOURNAL = re.compile(r'<a class="notranslate" href="[^"]+"[^>]*>\s*(.*?)<br>', re.S)
_RE_PUBLISHER = re.compile(r'<span class="font-italic">(.*?)</span>', re.S)
_RE_DOI = re.compile(r"https?://doi\.org/([^\s\"<&]+)")
_RE_ABSTRACT = re.compile(r'class="ml-2 mr-2 mt-2 mb-2"[^>]*>\s*(.*?)</div>', re.S)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    text = _TAG_RE.sub(" ", text or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_article_item(chunk: str) -> Article | None:
    m = _RE_TITLE.search(chunk)
    if not m:
        return None
    url = unescape(m.group(1)).strip()
    title = _strip_html(m.group(2))
    if len(title) < 8:
        return None

    year = None
    ym = _RE_YEAR.search(chunk)
    if ym:
        year = int(ym.group(1))

    issn = None
    im = _RE_ISSN.search(chunk)
    if im:
        parts = [p.strip() for p in im.group(1).split(",") if p.strip()]
        issn = parts[0].upper() if parts else None
        if issn and not _ISSN_RE.match(issn):
            issn = None

    authors_raw = ""
    am = _RE_AUTHORS.search(chunk)
    if am:
        authors_raw = _strip_html(am.group(1))
    authors = []
    for part in authors_raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if "," in part:
            family, given = part.split(",", 1)
            authors.append({"given": given.strip(), "family": family.strip(), "orcid": None})
        else:
            authors.append({"given": part, "family": "", "orcid": None})

    journal_title = None
    jm = _RE_JOURNAL.search(chunk)
    if jm:
        journal_title = _strip_html(jm.group(1))

    publisher = None
    pm = _RE_PUBLISHER.search(chunk)
    if pm:
        publisher = _strip_html(pm.group(1))

    doi = None
    dm = _RE_DOI.search(chunk)
    if dm:
        doi = dm.group(1).rstrip(".,;")
        if not _DOI_RE.match(doi):
            doi = None
    if doi:
        url = url or f"https://doi.org/{doi}"

    abstract = None
    abm = _RE_ABSTRACT.search(chunk)
    if abm:
        abstract = _strip_html(abm.group(1))
        if len(abstract) < 10:
            abstract = None

    pub_date = f"{year}-12-31" if year else None

    return Article(
        title=title,
        abstract=abstract,
        authors=authors,
        journal_title=journal_title,
        issn=issn,
        year=year,
        pub_date=pub_date,
        lang="es",
        url=url,
        source="latindex",
        source_id=doi or f"latindex:{abs(hash(title)) % (10 ** 10)}",
        doi=doi,
        access="oa",
    )


def _parse_articles_html(html: str) -> list[Article]:
    out = []
    for chunk in _ITEM_SPLIT.split(html):
        if "found-item" not in chunk:
            continue
        art = _parse_article_item(chunk)
        if art:
            out.append(art)
    return out


def search_articles(http: httpx.Client, query: str,
                    max_articles: int = 200) -> list[Article]:
    """Cosecha artículos del Descubridor por consulta (paginado, page-size=200)."""
    out: list[Article] = []
    page = 1
    while len(out) < max_articles:
        params = {
            "buscar": query,
            "idModBus": 3,
            "submit": "Buscar",
            "page": page,
            "page-size": ARTICLE_PAGE_SIZE,
        }
        try:
            r = http.get(ARTICLE_SEARCH_URL, params=params, timeout=60)
            r.raise_for_status()
        except Exception as e:
            log.warning("Latindex artículos %r pág %d: %s", query, page, e)
            break
        items = _parse_articles_html(r.text)
        if not items:
            break
        # Corte por año: el Descubridor ordena por relevancia; paramos en la
        # ventana (recientes primero) para no arrastrar décadas.
        fresh = [a for a in items if not a.year or a.year >= (date.today().year - 3)]
        out.extend(fresh)
        if len(items) < ARTICLE_PAGE_SIZE:
            break
        page += 1
        if page > 5:
            break
        # Cortesía: no saturar el Solr de Latindex
        import time
        time.sleep(config.REQUEST_DELAY + 0.2)
    log.info("Latindex Descubridor %r: %d artículos", query, len(out))
    return out[:max_articles]


def discover_articles(http: httpx.Client, max_articles: int = 400) -> list[Article]:
    """Cosecha artículos del campo desde el Descubridor (dedupe por DOI)."""
    p = profile.field_profile
    queries: list[str] = []
    for t in (p.topics or []):
        kws = (t.get("keywords_es") or [])
        if kws:
            queries.append(kws[0])
    queries.extend((p.editorial_axes or [])[:2])
    queries = list(dict.fromkeys(q.strip() for q in queries if q.strip()))[:6]

    seen_doi: set[str] = set()
    seen_sid: set[str] = set()
    out: list[Article] = []
    per_query = max(30, max_articles // max(len(queries), 1))
    for q in queries:
        if len(out) >= max_articles:
            break
        for a in search_articles(http, q, max_articles=per_query):
            if a.doi:
                key = f"doi:{a.doi.lower()}"
                if key in seen_doi:
                    continue
                seen_doi.add(key)
            else:
                key = f"sid:{a.source_id}"
                if key in seen_sid:
                    continue
                seen_sid.add(key)
            out.append(a)
    log.info("Latindex Descubridor: %d artículos únicos del campo", len(out))
    return out


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        prog="thinkuy-latindex",
        description="Descubre revistas del campo activo en el Catálogo 2.0 de Latindex")
    ap.add_argument("--no-cache", action="store_true", help="Forzar descarga fresca")
    ap.add_argument("--field", default=None, help="Perfil (THINKUY_FIELD si no)")
    ap.add_argument("--stats", action="store_true", help="Solo conteo por país")
    ap.add_argument("--articles", action="store_true",
                    help="Cosechar artículos del Descubridor (Catálogo 2.0)")
    ap.add_argument("--max-articles", type=int, default=400,
                    help="Tope de artículos a cosechar")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    import sys as _sys
    sys.path.insert(0, str(config.BACKEND_DIR.parent))
    if args.field:
        profile.reload(args.field)

    with httpx.Client(headers={"User-Agent": config.USER_AGENT},
                      follow_redirects=True, timeout=60.0) as c:
        if args.articles:
            arts = discover_articles(c, max_articles=args.max_articles)
            print("\n" + "=" * 70)
            print(f"LATINDEX DESCUBRIDOR — campo: {profile.field_profile.field_label}")
            print(f"Artículos únicos: {len(arts)}")
            for a in arts[:12]:
                print(f"  [{a.year}] {a.title[:70]} — {a.journal_title} ({a.doi or 'sin DOI'})")
            print("=" * 70)
            return 0
        found = discover_journals(c, use_cache=not args.no_cache)

    print("\n" + "=" * 70)
    print(f"LATINDEX CATÁLOGO 2.0 — campo: {profile.field_profile.field_label}")
    print(f"Revistas del campo: {len(found)}")
    if args.stats:
        by_country: dict[str, int] = {}
        for j in found:
            c = j["country"] or "?"
            by_country[c] = by_country.get(c, 0) + 1
        for c, n in sorted(by_country.items(), key=lambda x: -x[1]):
            print(f"  {c:20s} {n}")
    else:
        for j in sorted(found, key=lambda x: (x["country"] or "", x["title"] or "")):
            print(f"  [{j['country'] or '?'}] {j['title']} "
                  f"(e-ISSN {j['issn_online']})")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())