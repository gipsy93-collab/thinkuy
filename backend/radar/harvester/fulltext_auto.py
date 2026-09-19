"""Auto-ingesta de textos completos vía Europe PMC (XML JATS, vía limpia y legal).

Cubre la vía automática del mapa epistemológico: para artículos del catálogo sin
fulltext, resuelve su PMCID, descarga el XML, lo convierte a Markdown y ejecuta la
ruta integral (fulltext + contextos + auto-ingerir citados). Los PDFs manuales
siguen entrando por POST /api/fulltext/extract-pdf. No se descargan PDFs.
"""
from __future__ import annotations

import logging
import time

import httpx

from .. import config, db, text_extractor
from . import europepmc

log = logging.getLogger("radar.fulltext_auto")


def resolve_pmc(http: httpx.Client, article: dict) -> tuple[str | None, str | None]:
    """Devuelve (source, id) de Europe PMC para el artículo, o (None, None)."""
    if (article.get("source") or "") == "europepmc" and article.get("source_id"):
        sid = str(article["source_id"]).strip()
        if sid.upper().startswith("PMC"):
            return "PMC", sid
        return None, None
    doi = (article.get("doi") or "").strip()
    if not doi:
        return None, None
    try:
        resp = http.get(
            f"{europepmc.REST}/search",
            params={"query": f'DOI:"{doi}"', "format": "json", "pageSize": 5},
            timeout=30,
        )
        resp.raise_for_status()
        results = (resp.json().get("resultList") or {}).get("result") or []
    except Exception as e:
        log.warning("Europe PMC resolve %s: %s", doi, e)
        return None, None
    for r in results:
        if not isinstance(r, dict):
            continue
        pmcid = (r.get("pmcid") or "").strip()
        if pmcid:
            return "PMC", pmcid
    return None, None


def ingest_one(conn, http: httpx.Client, article: dict) -> dict | None:
    """Ingiere el fulltext de un artículo. Devuelve stats o None si no hay XML."""
    doi = (article.get("doi") or "").strip().lower()
    if not doi:
        return None
    if db.get_article_fulltext(conn, doi):
        return {"skipped": True}
    source, pmc_id = resolve_pmc(http, article)
    if not source:
        return None
    xml_text = europepmc.fulltext_xml(http, source, pmc_id)
    if not xml_text:
        return None
    md = text_extractor.extract_xml_to_markdown(xml_text)
    if not md:
        return None
    res = text_extractor.ingest_fulltext_and_contexts(
        conn,
        citing_doi=doi,
        full_text=md["full_text"],
        sections=md.get("sections"),
        word_count=md.get("word_count"),
        page_count=None,
        cited_dois=None,
        references_texts=md.get("references"),
        http=http,
        auto_ingest_refs=True,
    )
    return {"doi": doi, **{k: v for k, v in res.items() if k != "contexts"}}


def backfill_fulltexts(conn, http: httpx.Client | None = None, limit: int = 10,
                       delay: float | None = None) -> dict:
    """Rellena fulltexts faltantes (los más citados primero)."""
    delay = delay if delay is not None else config.REQUEST_DELAY
    rows = conn.execute(
        """SELECT a.* FROM articles a LEFT JOIN article_fulltext f ON f.doi = a.doi
           WHERE f.doi IS NULL AND a.doi IS NOT NULL
           ORDER BY (a.source = 'europepmc') DESC, COALESCE(a.cited_by, 0) DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    close_http = http is None
    client = http or httpx.Client(
        headers={"User-Agent": config.USER_AGENT}, follow_redirects=True, timeout=45.0
    )
    ok, skipped, contexts, cited = 0, 0, 0, 0
    try:
        for r in rows:
            art = db._row_to_article(r)
            try:
                res = ingest_one(conn, client, art)
            except Exception as e:
                log.warning("fulltext %s: %s", art.get("doi"), e)
                res = None
            if not res:
                continue
            if res.get("skipped"):
                skipped += 1
                continue
            ok += 1
            contexts += res.get("citation_contexts_extracted", 0)
            cited += len(res.get("ingested_cited", []))
            time.sleep(delay)
    finally:
        if close_http:
            client.close()
    try:
        db.log_harvest(conn, "fulltext_auto", "ok", ok, ok,
                       f"contextos={contexts} citados_ingeridos={cited}")
    except Exception:
        pass
    return {"processed": len(rows), "ingested": ok, "skipped": skipped,
            "contexts": contexts, "cited_ingested": cited}
