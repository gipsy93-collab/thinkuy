"""Descubrimiento en vivo por tema/pregunta (Live Search / On-demand Harvester).

Permite buscar activamente en OpenAlex, Crossref, Europe PMC y Latindex por
términos temáticos, recuperando publicaciones recientes e insertándolas de
inmediato en el catálogo local para enriquecer el Radar de Proximidad y traer
nuevos autores emergentes a la órbita.

Si el tema nombra a una persona ('Torres Salinas', un ORCID...), además resuelve
al autor en OpenAlex y trae sus obras más citadas por `author.id`: la búsqueda
textual sola nunca encuentra a nadie por su nombre (solo mira títulos/resúmenes).
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import date, timedelta
import httpx

from .. import config, db
from ..normalize import norm
from . import crossref, europepmc, latindex, openalex
from ..network import author_identity_map, canonical_author_id, invalidate_network_cache

log = logging.getLogger("radar.live_search")
_DISCOVERY_LOCK = threading.Lock()


def _existing_author_identities(conn) -> tuple[list[dict], set[str]]:
    """Artículos existentes e identidades canónicas ya presentes en el catálogo."""
    rows = conn.execute("SELECT * FROM articles WHERE authors IS NOT NULL").fetchall()
    articles = [db._row_to_article(row) for row in rows]
    identity_map = author_identity_map(articles)
    identities: set[str] = set()
    for article in articles:
        for author in article.get("authors") or []:
            if not isinstance(author, dict):
                continue
            identity = canonical_author_id(author, identity_map)
            if identity:
                identities.add(identity)
    return articles, identities


def _openalex_topic_search(client: httpx.Client, query: str, date_from: str, limit: int) -> list:
    """Busca publicaciones recientes por tema en OpenAlex."""
    params = {
        "search": query,
        "filter": f"type:article|review,from_publication_date:{date_from}",
        "sort": "publication_date:desc",
        "per-page": min(max(limit, 1), 50),
        "mailto": config.MAILTO,
    }
    resp = client.get(openalex.BASE, params=params, headers=config.openalex_headers())
    resp.raise_for_status()
    data = resp.json()
    return data.get("results") or []


def _crossref_topic_search(client: httpx.Client, query: str, date_from: str, limit: int) -> list:
    """Busca publicaciones recientes por tema bibliográfico en Crossref."""
    params = {
        "query.bibliographic": query,
        "filter": f"type:journal-article,from-pub-date:{date_from}",
        "rows": min(max(limit, 1), 50),
        "sort": "published",
        "order": "desc",
        "select": "DOI,title,author,container-title,issued,volume,issue,page,abstract,URL,ISSN,subject,license,is-referenced-by-count",
        "mailto": config.MAILTO,
    }
    resp = client.get(crossref.BASE, params=params)
    resp.raise_for_status()
    return (resp.json().get("message") or {}).get("items") or []


def _europepmc_topic_search(client: httpx.Client, query: str, date_from: str, limit: int) -> list:
    """Busca publicaciones recientes por tema en Europe PMC (acceso libre, sin API key)."""
    return europepmc.search(client, query, limit=limit, date_from=date_from)


def _latindex_topic_search(client: httpx.Client, query: str, limit: int) -> list:
    """Busca artículos iberoamericanos recientes por tema en el Descubridor Latindex."""
    return latindex.search_articles(client, query, max_articles=limit)


def _openalex_authors_url() -> str:
    return openalex.BASE.rsplit("/works", 1)[0] + "/authors"


def _openalex_author_search(client: httpx.Client, query: str, limit: int = 3) -> list:
    """Resuelve un posible nombre de persona a autores de OpenAlex."""
    resp = client.get(
        _openalex_authors_url(),
        params={"search": query, "per-page": min(max(limit, 1), 5), "mailto": config.MAILTO},
        headers=config.openalex_headers(),
    )
    resp.raise_for_status()
    return resp.json().get("results") or []


def _openalex_author_by_orcid(client: httpx.Client, orcid: str) -> dict | None:
    """Resuelve un ORCID directamente al autor de OpenAlex (sin búsqueda textual)."""
    url = f"{_openalex_authors_url()}/https://orcid.org/{orcid}"
    resp = client.get(url, params={"mailto": config.MAILTO}, headers=config.openalex_headers())
    if resp.status_code == 200:
        return resp.json()
    return None


def _openalex_author_works(client: httpx.Client, author_id: str, limit: int) -> list:
    """Obras representativas de un autor (las más citadas, sin ventana temporal:
    para una persona importa su obra de referencia, no solo lo último)."""
    aid = author_id.split("/")[-1]
    resp = client.get(
        openalex.BASE,
        params={
            "filter": f"author.id:{aid},type:article|review",
            "sort": "cited_by_count:desc",
            "per-page": min(max(limit, 1), 25),
            "mailto": config.MAILTO,
        },
        headers=config.openalex_headers(),
    )
    resp.raise_for_status()
    return resp.json().get("results") or []


def _topic_orcid(topic: str) -> str | None:
    m = re.search(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", topic or "")
    return m.group(0) if m else None


def _topic_person_candidates(topic: str) -> list[str]:
    """Fragmentos del tema que podrían ser nombre de persona (2+ tokens).

    Incluye el tema completo más ventanas de 2-3 tokens capitalizados, para
    consultas mixtas como 'altmetrics Daniel Torres Salinas'.
    """
    words = (topic or "").split()
    cands: list[str] = []
    if len(words) >= 2:
        cands.append(" ".join(words))
    for n in (3, 2):
        for i in range(len(words) - n + 1):
            win = words[i:i + n]
            if all(w[:1].isupper() and len(norm(w)) >= 3 for w in win):
                cands.append(" ".join(win))
    return list(dict.fromkeys(c for c in cands if len(c.split()) >= 2))


def _author_matches_candidate(candidate: str, display_name: str | None) -> bool:
    """¿Es este autor de OpenAlex la persona nombrada por el candidato?

    Exige 2+ tokens significativos en común Y cobertura >= 50% del nombre más
    largo: así 'Torres Salinas' casa con 'Daniel Torres-Salinas' pero
    'comunicación científica' no casa con una institución de 12 palabras que
    la contenga ('Observatorio de la Comunicacion Cientifica y Medica...').
    """
    cn = norm(candidate)
    an = norm(display_name or "")
    if not cn or not an:
        return False
    cn_set, an_set = set(cn.split()), set(an.split())
    inter = cn_set & an_set
    if len([t for t in inter if len(t) >= 4]) < 2:
        return False
    coverage = len(inter) / max(len(cn_set), len(an_set))
    return coverage >= 0.5


def _ingest_author_works(client: httpx.Client, author: dict, limit: int,
                         articles_by_doi: dict, source_stats: dict) -> None:
    """Trae las obras más citadas del autor y las suma al lote por descubrir."""
    aname = author.get("display_name") or "autor"
    works = _openalex_author_works(client, str(author.get("id") or ""), limit)
    a_found = 0
    for item in works:
        art = openalex.parse_item(item)
        if not art or not art.title:
            continue
        doi = (art.doi or "").strip().lower()
        if not doi:
            continue
        a_found += 1
        articles_by_doi.setdefault(doi, ("openalex", art))
    source_stats[f"autor:{aname}"] = {"status": "ok", "found": a_found, "new": 0}


def discover_by_topic(
    conn,
    topic: str,
    days: int = 730,
    max_results: int = 30,
    http: httpx.Client | None = None
) -> dict:
    """Busca en OpenAlex y Crossref publicaciones recientes que coincidan con `topic` y las guarda."""
    if not topic or not topic.strip():
        return {"found": 0, "new": 0, "authors_added": 0, "journals_added": 0, "sources": {}}

    query = topic.strip()
    safe_days = max(1, int(days or 730))
    safe_max_results = max(1, min(int(max_results or 30), 50))
    date_from = (date.today() - timedelta(days=safe_days)).isoformat()

    close_http = http is None
    client = http or httpx.Client(
        headers={"User-Agent": config.USER_AGENT},
        follow_redirects=True,
        timeout=30.0,
    )

    found = 0
    new = 0
    journals_added = 0
    new_author_ids: set[str] = set()
    source_stats: dict[str, dict] = {}

    try:
        openalex_limit = safe_max_results
        crossref_limit = min(max(10, safe_max_results // 2), 20)
        europepmc_limit = min(max(5, safe_max_results // 2), 15)
        latindex_limit = min(max(5, safe_max_results // 3), 10)
        source_items = [
            ("openalex", lambda: _openalex_topic_search(client, query, date_from, openalex_limit)),
            ("crossref", lambda: _crossref_topic_search(client, query, date_from, crossref_limit)),
            ("europepmc", lambda: _europepmc_topic_search(client, query, date_from, europepmc_limit)),
            ("latindex", lambda: _latindex_topic_search(client, query, latindex_limit)),
        ]
        articles_by_doi = {}
        # Paso de autor: si el tema nombra a una persona, resolverla en OpenAlex
        # y traer sus obras más citadas por author.id. Un solo autor resuelto
        # basta (evita mezclar homónimos).
        author_limit = min(max(10, safe_max_results // 2), 20)
        orcid = _topic_orcid(query)
        if orcid:
            try:
                resolved = _openalex_author_by_orcid(client, orcid)
                if resolved and resolved.get("id"):
                    _ingest_author_works(client, resolved, author_limit,
                                         articles_by_doi, source_stats)
            except Exception as exc:
                log.warning("Error resolviendo ORCID %s: %s", orcid, exc)
        else:
            for candidate in _topic_person_candidates(query)[:3]:
                try:
                    matches = _openalex_author_search(client, candidate, limit=3)
                except Exception as exc:
                    log.warning("Error resolviendo autor para %r: %s", candidate, exc)
                    continue
                # Preferir autores con ORCID (personas reales verificables)
                # sobre entidades sin identificador (observatorios, colectivos).
                ordered = sorted(matches, key=lambda m: bool((m or {}).get("orcid")), reverse=True)
                picked = next(
                    (m for m in ordered
                     if _author_matches_candidate(candidate, (m or {}).get("display_name"))),
                    None,
                )
                if not picked or not picked.get("id"):
                    continue
                try:
                    _ingest_author_works(client, picked, author_limit,
                                         articles_by_doi, source_stats)
                except Exception as exc:
                    aname = picked.get("display_name") or candidate
                    log.warning("Error trayendo obras de %s: %s", aname, exc)
                    source_stats[f"autor:{aname}"] = {
                        "status": "error", "found": 0, "new": 0, "error": str(exc)}
                break
        # OpenAlex y Crossref devuelven JSON crudo (requieren parser);
        # Europe PMC y Latindex ya devuelven objetos Article.
        item_parsers = {"openalex": openalex.parse_item, "crossref": crossref.parse_item}
        for source_name, search_call in source_items:
            try:
                items = search_call()
                source_found = 0
                parser = item_parsers.get(source_name)
                for item in items:
                    art = parser(item) if parser else item
                    if not art or not art.title:
                        continue
                    doi = (art.doi or "").strip().lower()
                    if not doi:
                        continue
                    source_found += 1
                    articles_by_doi.setdefault(doi, (source_name, art))
                source_stats[source_name] = {"status": "ok", "found": source_found, "new": 0}
            except Exception as exc:
                log.warning("Error en descubrimiento en vivo %s: %s", source_name, exc)
                source_stats[source_name] = {"status": "error", "found": 0, "new": 0, "error": str(exc)}

        existing_articles, existing_authors = _existing_author_identities(conn)
        combined_identity_map = author_identity_map(
            existing_articles + [art.db_row() for _, art in articles_by_doi.values()]
        )
        with _DISCOVERY_LOCK:
            for source_name, art in articles_by_doi.values():
                found += 1
                row = art.db_row()
                status, _ = db.upsert_article(conn, row)
                journal_is_new, _ = db.ensure_journal_from_article(
                    conn,
                    source=source_name,
                    title=row.get("journal_title"),
                    issn=row.get("issn"),
                )
                if journal_is_new:
                    journals_added += 1
                if status == "new":
                    new += 1
                    source_stats[source_name]["new"] += 1
                    for author in art.authors or []:
                        if not isinstance(author, dict):
                            continue
                        identity = canonical_author_id(author, combined_identity_map)
                        if identity and identity not in existing_authors:
                            existing_authors.add(identity)
                            new_author_ids.add(identity)

            if found > 0:
                invalidate_network_cache()
            if new > 0:
                db.rebuild_keywords(conn)
                db.rebuild_author_stats(conn)
                db.rebuild_anchor_signals(conn)

            if found > 0:
                openalex_stats = source_stats.get("openalex", {})
                crossref_stats = source_stats.get("crossref", {})
                db.log_harvest(conn, "openalex_live", openalex_stats.get("status", "ok"),
                                openalex_stats.get("found", 0), openalex_stats.get("new", 0),
                                f"topic='{query}'")
                db.log_harvest(conn, "crossref_live", crossref_stats.get("status", "ok"),
                                crossref_stats.get("found", 0), crossref_stats.get("new", 0),
                                f"topic='{query}'")

            log.info("Descubrimiento en vivo para '%s': %d encontrados, %d nuevos", query, found, new)
            errors = [
                f"{name}: {info.get('error')}"
                for name, info in source_stats.items()
                if info.get("status") == "error"
            ]
            result = {
                "topic": query,
                "found": found,
                "new": new,
                "authors_added": len(new_author_ids),
                "journals_added": journals_added,
                "sources": source_stats,
            }
            if found == 0 and errors:
                result["error"] = "; ".join(errors)
            return result

    except Exception as e:
        log.warning("Error en descubrimiento en vivo: %s", e)
        return {"topic": query, "found": found, "new": new, "authors_added": len(new_author_ids),
                "journals_added": journals_added, "sources": source_stats, "error": str(e)}
    finally:
        if close_http:
            client.close()
