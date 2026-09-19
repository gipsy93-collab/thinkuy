"""Subrouter de la API de Thinkuy."""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Body, HTTPException, Query

from ... import author_match, config, db, scivis
from ..common import (
    _as_int,
)

router = APIRouter(tags=['editorial'])
log = logging.getLogger('radar.api.editorial')

@router.get("/api/match/journals")
def match_journals(
    article_id: int | None = Query(None, description="ID de artículo del corpus para evaluar encaje"),
    topic: str | None = Query(None, description="Título, resumen o palabras clave de la propuesta"),
    limit: int = Query(6, ge=1, le=20)
):
    """Match de Revistas & CFPs: evalúa afinidad temática con números especiales (CFPs) y líneas editoriales."""
    conn = db.connect()
    try:
        return author_match.find_journal_matches(
            conn,
            article_id=article_id,
            topic_query=topic,
            limit=limit,
        )
    finally:
        conn.close()


@router.get("/api/match/reviewers")
def match_reviewers(
    article_id: int | None = Query(None, description="ID de artículo del corpus para buscar evaluadores"),
    author_name: str | None = Query(None, description="Nombre del autor para excluir conflictos de interés"),
    topic: str | None = Query(None, description="Tema o línea de investigación del manuscrito"),
    limit: int = Query(6, ge=1, le=20)
):
    """Match de Revisores / Editores: sugiere evaluadores pares con especialidad comprobada y sin conflicto de interés."""
    conn = db.connect()
    try:
        return author_match.find_reviewer_matches(
            conn,
            article_id=article_id,
            author_name=author_name,
            topic_query=topic,
            limit=limit,
        )
    finally:
        conn.close()


@router.get("/api/authors/match")
def author_matches(
    article_id: int | None = Query(None, description="ID de artículo del corpus para buscar pares"),
    author_name: str | None = Query(None, description="Nombre de autor del corpus"),
    topic: str | None = Query(None, description="Tema o línea de investigación"),
    limit: int = Query(6, ge=1, le=20)
):
    """Ruta de compatibilidad retroactiva hacia el Match de Revisores."""
    conn = db.connect()
    try:
        return author_match.find_reviewer_matches(
            conn,
            article_id=article_id,
            author_name=author_name,
            topic_query=topic,
            limit=limit,
        )
    finally:
        conn.close()


@router.get("/api/scivis/audit")
def scivis_audit_endpoint(
    query: Optional[str] = Query(None, description="Nombre de revista, ISSN o campo temático"),
    q: Optional[str] = Query(None, description="Alias para query"),
    refresh: int = Query(0, ge=0, le=1, description="1 fuerza una nueva medición (ignora la caché TTL)"),
):
    """Audita el ecosistema editorial de una revista o campo: SCIVIS, centralidad armónica, benchmarking y editores."""
    target_q = (query or q or "").strip()
    if not target_q:
        raise HTTPException(status_code=400, detail="Debe proporcionar el parámetro 'query' o 'q'")
    return scivis.audit_journal_ecosystem(target_q, refresh=bool(refresh))


@router.get("/api/scivis/ranking")
def scivis_ranking_endpoint(
    limit: int = Query(15, ge=1, le=50, description="Número de revistas en el ranking"),
):
    """Ranking cibermétrico SCIVIS: revistas del catálogo por Centralidad Armónica real del Web Graph de Common Crawl."""
    return {"ranking": scivis.get_scivis_ranking(limit=limit)}


@router.get("/api/scivis/in-out-links")
def scivis_in_out_links_endpoint(
    domain: Optional[str] = Query(None, description="Dominio de la revista"),
    query: Optional[str] = Query(None, description="Nombre o ISSN de la revista"),
):
    """Auditoría hipertextual de In-Links (Wikipedia, Substack, OpenAlex) y Out-Links (Zenodo, DOIs, etc.)."""
    target_q = (query or domain or "").strip()
    if not target_q:
        raise HTTPException(status_code=400, detail="Debe proporcionar 'domain' o 'query'")
    audit = scivis.audit_journal_ecosystem(target_q)
    return audit.get("in_out_audit") or {}


@router.post("/api/editorial/journal/profile")
def editorial_journal_profile_endpoint(payload: dict = Body(default={})):
    """**Modo Revista, escalón 1**: huella editorial de una revista OJS por OAI-PMH.

    Detecta el endpoint `/oai` de la revista, cosecha su metadata y devuelve el **Editorial
    DNA**: qué publica, desde cuándo, en qué idiomas, con qué palabras clave y con qué
    cobertura de resumen y DOI. Con `guardar=true` ingresa los artículos al catálogo local
    para que el resto de la herramienta los use.

    Coste medido: una revista completa en **una petición paginada** (0,17 s por artículo),
    frente a una descarga por ficha de la ruta por artículo.
    """
    from ...harvester import ojs_oai

    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(422, "url es obligatoria")

    max_records = _as_int(payload.get("max_records"), default=200, minimum=1, maximum=2000)
    date_from = str(payload.get("date_from") or "").strip() or None
    set_spec = str(payload.get("set_spec") or "").strip() or None
    guardar = bool(payload.get("guardar", False))
    incluir_articulos = bool(payload.get("incluir_articulos", False))

    client = httpx.Client(headers={"User-Agent": config.USER_AGENT},
                          follow_redirects=True, timeout=60.0)
    try:
        resultado = ojs_oai.harvest_from_url(url, client, max_records=max_records,
                                            date_from=date_from, set_spec=set_spec)
        articulos = resultado.pop("articulos", [])
        if guardar and articulos:
            conn = db.connect()
            try:
                nuevos = 0
                for fila in articulos:
                    try:
                        status, _ = db.upsert_article(conn, fila)
                    except Exception as e:
                        log.warning("no se pudo guardar %s: %s", fila.get("title"), e)
                        continue
                    if status == "new":
                        nuevos += 1
                resultado["guardados"] = {"total": len(articulos), "nuevos": nuevos}
            finally:
                conn.close()
        if incluir_articulos:
            resultado["articulos"] = articulos
        return {"status": "ok" if resultado.get("endpoint") else "sin_endpoint", **resultado}
    finally:
        client.close()

