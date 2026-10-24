"""Subrouter de la API de Thinkuy."""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, Body, File, HTTPException, Query, Request, Response, UploadFile

from ... import citation_graph, db, importer, screening_ranker
from ...matching import match_article, parse_keywords, rank_articles
from ..common import (
    _as_int,
    _extract_owner_id,
)

router = APIRouter(tags=['screening'])
log = logging.getLogger('radar.api.screening')

@router.post("/api/review/protocol")
def create_protocol_endpoint(request: Request, payload: dict = Body(...)):
    """Crea y persiste un nuevo protocolo de revisión sistemática (PICO/SPIDER/JBI)."""
    title = payload.get("title")
    if not title:
        raise HTTPException(400, "El título del protocolo es obligatorio")
    owner_id = _extract_owner_id(request, payload.get("owner_id"))
    conn = db.connect()
    try:
        pid = db.save_protocol(conn, payload, owner_id=owner_id)
        saved = db.get_protocol(conn, pid, owner_id=owner_id)
        return {"status": "ok", "protocol_id": pid, "protocol": saved}
    finally:
        conn.close()


@router.get("/api/review/protocols")
def list_protocols_endpoint(request: Request, limit: int = Query(50, ge=1, le=100), owner_id: Optional[str] = Query(None)):
    """Lista los protocolos de revisión sistemática almacenados."""
    user_id = _extract_owner_id(request, owner_id)
    conn = db.connect()
    try:
        return {"protocols": db.list_protocols(conn, limit=limit, owner_id=user_id)}
    finally:
        conn.close()


@router.get("/api/review/protocol/{protocol_id}")
def get_protocol_endpoint(request: Request, protocol_id: int, owner_id: Optional[str] = Query(None)):
    """Obtiene el detalle de un protocolo de revisión sistemática."""
    user_id = _extract_owner_id(request, owner_id)
    conn = db.connect()
    try:
        p = db.get_protocol(conn, protocol_id, owner_id=user_id)
        if not p:
            raise HTTPException(404, "Protocolo no encontrado")
        return p
    finally:
        conn.close()


@router.post("/api/review/protocol/{protocol_id}/status")
def set_protocol_status_endpoint(request: Request, protocol_id: int, payload: dict = Body(...)):
    """Avanza el estado PRISMA del protocolo: draft → screening → extracting → completed."""
    user_id = _extract_owner_id(request, payload.get("owner_id"))
    conn = db.connect()
    try:
        try:
            p = db.update_protocol_status(conn, protocol_id, payload.get("status"), owner_id=user_id)
        except ValueError as e:
            raise HTTPException(422, str(e))
        if not p:
            raise HTTPException(404, "Protocolo no encontrado")
        return {"status": "ok", "protocol": p}
    finally:
        conn.close()


@router.post("/api/review/systematic")
def systematic_review_endpoint(payload: dict = Body(...)):
    """Agente A.1 Metodólogo: informe PRISMA en 7 fases sobre un corpus verificado.

    Body: {inquiry (requerido), dois? (corpus explícito), boolean_query? (Fase 2
    ejecutable: se parsea a keywords del motor), limit? (tope si se rankea)}.
    Aplica la heurística 30-300 con mensajes y audita la extracción contra el corpus.
    """
    from ... import librarian
    from ...matching import parse_boolean_query

    inquiry = str(payload.get("inquiry") or "").strip()
    if not inquiry:
        raise HTTPException(422, "inquiry es obligatorio")
    limit = _as_int(payload.get("limit"), default=30, minimum=5, maximum=100)
    dois = [str(d).strip().lower() for d in (payload.get("dois") or []) if str(d).strip()]
    protocol_id = payload.get("protocol_id")
    boolean_query = str(payload.get("boolean_query") or "").strip()

    conn = db.connect()
    try:
        parsed: dict = {}
        corpus = []
        if dois:
            placeholders = ",".join(["?"] * len(dois))
            rows = conn.execute(
                f"SELECT * FROM articles WHERE doi IN ({placeholders})", dois
            ).fetchall()
            corpus = [db._row_to_article(r) for r in rows]
        elif protocol_id:
            # Artículos incluidos en el cribado del protocolo activo
            try:
                # Con dos etapas, el corpus final es el incluido a texto completo; sin ellas,
                # el incluido de título/resumen (comportamiento previo).
                tiene_ft = conn.execute(
                    "SELECT 1 FROM article_screenings WHERE protocol_id = ? AND stage = 'full_text' LIMIT 1",
                    (int(protocol_id),),
                ).fetchone()
                etapa = "full_text" if tiene_ft else "title_abstract"
                screenings = db.list_screenings(conn, int(protocol_id), decision="included", stage=etapa)
                if not screenings:
                    all_scr = db.list_screenings(conn, int(protocol_id), stage=etapa)
                    screenings = [s for s in all_scr if s.get("decision") != "excluded"]
                if screenings:
                    inc_dois = [s["doi"].strip().lower() for s in screenings if s.get("doi")]
                    placeholders = ",".join(["?"] * len(inc_dois))
                    rows = conn.execute(
                        f"SELECT * FROM articles WHERE doi IN ({placeholders})", inc_dois
                    ).fetchall()
                    corpus = [db._row_to_article(r) for r in rows]
                    chartings = {
                        c["doi"].strip().lower(): c
                        for c in db.list_charting(conn, int(protocol_id), limit=300)
                        if c.get("doi")
                    }
                    for art in corpus:
                        d = (art.get("doi") or "").strip().lower()
                        if d in chartings:
                            art["charting"] = chartings[d]
            except Exception:
                corpus = []

        if not corpus:
            if boolean_query:
                # Fase 2 ejecutable: la booleana del LLM maneja el motor
                parsed = parse_boolean_query(boolean_query)
                kws = parsed.get("keywords") or parse_keywords(inquiry)
            else:
                kws = parse_keywords(inquiry)
                if not kws:
                    kws = [inquiry]
            rows = conn.execute("SELECT * FROM articles").fetchall()
            arts = [db._row_to_article(r) for r in rows]
            ranked = rank_articles(arts, kws)
            corpus = [a for a in ranked if a.get("match_score", 0) > 0]

        # Heurística de muestra 30-300 sobre lo RECUPERADO (no sobre la página):
        # con truncado documentado, no silencioso.
        total_found = len(corpus)
        if total_found < 30:
            sample_status = "narrow"
            sample_message = (
                f"Tema muy específico: {total_found} artículos. Se sugiere ampliar "
                "términos, quitar filtros de año o relajar criterios."
            )
        elif total_found > 300:
            sample_status = "broad"
            sample_message = (
                f"Tema inmanejable: {total_found} artículos. Se truncó a 300 para el "
                "informe; se sugiere acotar por año, área o añadir el comparador (C)."
            )
            corpus = corpus[:300]
        else:
            sample_status = "optimal"
            sample_message = f"Muestra en rango óptimo PRISMA: {total_found} artículos."
        engine_note = f"{sample_message} Rango óptimo: 30 a 300."

        res = librarian.run_systematic_review(inquiry, corpus, engine_note=engine_note)
        audit = librarian.audit_extraction(res.get("report"), corpus) if res.get("status") == "ok" else {
            "rows_checked": 0, "unmatched": [], "foreign_dois": [], "clean": True}
        return {"inquiry": inquiry, **res,
                "sample_status": sample_status, "sample_message": sample_message,
                "total_found": total_found,
                "boolean_logic": parsed.get("boolean_logic") if parsed else None,
                "audit": audit,
                "corpus": [{"doi": a.get("doi"), "title": a.get("title"),
                            "year": a.get("year")} for a in corpus[:limit]]}
    finally:
        conn.close()


@router.post("/api/review/protocol/{protocol_id}/screen")
def screen_article_endpoint(request: Request, protocol_id: int, payload: dict = Body(...)):
    """Registra la decisión de screening (included/excluded/maybe/pending) de un artículo."""
    doi = payload.get("doi")
    if not doi:
        raise HTTPException(400, "El campo 'doi' es obligatorio")
    user_id = _extract_owner_id(request, payload.get("owner_id"))
    conn = db.connect()
    try:
        try:
            result = db.save_screening(
                conn, protocol_id,
                doi=doi,
                decision=payload.get("decision", "pending"),
                reason=payload.get("reason"),
                article_id=payload.get("article_id"),
                screened_by=payload.get("screened_by", "researcher"),
                owner_id=user_id,
                stage=payload.get("stage", "title_abstract"),
            )
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"status": "ok", "screening": result}
    finally:
        conn.close()


@router.post("/api/review/protocol/{protocol_id}/screen-batch")
def screen_batch_endpoint(request: Request, protocol_id: int, payload: dict = Body(...)):
    """Registra decisiones de screening en lote para múltiples artículos.

    **Aquí es donde se persiste**, no al buscar: si el item trae el artículo completo, se indexa
    y se enlaza. Así el catálogo solo crece con obras que el investigador **decidió** trabajar, y
    no con todo lo que pasó por sus búsquedas (medido: una búsqueda clínica metía 95 artículos
    ajenos al catálogo). Buscar deja de ser una escritura.
    """
    items = payload.get("items", [])
    if not items:
        raise HTTPException(400, "El campo 'items' (lista) es obligatorio")
    user_id = _extract_owner_id(request, payload.get("owner_id"))
    conn = db.connect()
    try:
        results = []
        for item in items:
            doi = item.get("doi")
            if not doi:
                continue
            article_id = item.get("article_id")
            articulo = item.get("article")
            if isinstance(articulo, dict) and articulo.get("title"):
                try:
                    _, article_id = db.upsert_article(conn, articulo)
                except Exception as e:
                    log.debug("no se pudo indexar al transferir a cribado: %s", e)
            try:
                r = db.save_screening(
                    conn, protocol_id,
                    doi=doi,
                    decision=item.get("decision", "pending"),
                    reason=item.get("reason"),
                    article_id=article_id,
                    owner_id=user_id,
                    stage=item.get("stage", "title_abstract"),
                )
                results.append(r)
            except ValueError:
                continue
        return {"status": "ok", "screened": len(results), "results": results}
    finally:
        conn.close()


@router.post("/api/review/protocol/{protocol_id}/harvest-search")
def harvest_search_endpoint(protocol_id: int, payload: dict = Body(...)):
    """Cosecha federada en tiempo real (OpenAlex + OpenAIRE Graph + Dialnet) y las agrega a screening del protocolo.

    Filtro de años **opcional** (`year_from`/`year_to`, o `date_from`/`date_to`): solo se aplica
    si el investigador lo envía. Sin extremos, la búsqueda no se acota — buscar no debe estrechar
    el universo por defecto.
    """
    query = str(payload.get("query") or "").strip()
    limit = _as_int(payload.get("limit"), default=100, minimum=5, maximum=250)

    def _anio(valor):
        try:
            return int(str(valor).strip())
        except (TypeError, ValueError):
            return None

    year_from = _anio(payload.get("year_from", payload.get("date_from")))
    year_to = _anio(payload.get("year_to", payload.get("date_to")))
    conn = db.connect()
    try:
        protocol = db.get_protocol(conn, protocol_id)
        if not protocol:
            raise HTTPException(404, "Protocolo no encontrado")
        if not query:
            query = protocol.get("research_question") or protocol.get("title") or ""
        if not query:
            raise HTTPException(400, "Consulta de búsqueda vacía")

        from ...harvester import live_probe
        probe_res = live_probe.probe_topic(query=query, limit=limit, federated=True,
                                           year_from=year_from, year_to=year_to)
        articles = (probe_res.get("articles") or []) if probe_res else []
        total_matched = probe_res.get("total_matched") or len(articles) if probe_res else 0
        added = 0
        enriched_articles = []
        for art in articles:
            raw_doi = art.get("doi")
            if isinstance(raw_doi, dict):
                raw_doi = raw_doi.get("value") or raw_doi.get("id") or ""
            elif isinstance(raw_doi, list):
                raw_doi = raw_doi[0] if raw_doi else ""
            doi = str(raw_doi or "").strip().lower()

            raw_title = art.get("title")
            if isinstance(raw_title, dict):
                raw_title = raw_title.get("value") or raw_title.get("title") or ""
            elif isinstance(raw_title, list):
                raw_title = raw_title[0] if raw_title else ""
            art["title"] = str(raw_title or "Sin título").strip()

            raw_issn = art.get("issn")
            if isinstance(raw_issn, (dict, list)):
                raw_issn = str(raw_issn)
            art["issn"] = str(raw_issn or "").strip()

            if not doi:
                art_src = art.get("source") or art.get("source_engine") or "ref"
                clean_sid = re.sub(r'[^a-zA-Z0-9_\-\.:/]', '_', str(art.get("source_id") or ""))
                # Se pasa a minúsculas: si no, `openalex:W123` y `openalex:w123` convivían como
                # dos obras distintas (caso real medido 22-09-2026).
                doi = (f"{art_src}:{clean_sid}" if clean_sid
                       else f"{art_src}:{abs(hash(art.get('title', '')))}").lower()
            art["doi"] = doi

            art["role"] = citation_graph.classify_epistemic_role(art)
            try:
                _, art_id = db.upsert_article(conn, art)
                art["id"] = art_id
                existing = conn.execute(
                    "SELECT id FROM article_screenings WHERE protocol_id = ? AND LOWER(doi) = ?",
                    (protocol_id, doi),
                ).fetchone()
                if not existing:
                    db.save_screening(conn, protocol_id, doi=doi, decision="pending", article_id=art_id)
                    added += 1
                enriched_articles.append(art)
            except Exception as e:
                log.warning("Fallo al persistir obra federada en screening: %s", e)
                continue
        # Registro de identificación PRISMA 2020 (ítem 6): una fila por fuente y búsqueda, con
        # cuántos registros devolvió, la consulta usada, el límite temporal y la fecha. De aquí
        # salen la identificación y los duplicados removidos del diagrama de flujo.
        fuentes_crudas = (probe_res or {}).get("fuentes_crudas") or {}
        consulta_usada = (probe_res or {}).get("consulta_usada") or query
        for fuente, n in fuentes_crudas.items():
            try:
                db.log_protocol_search(conn, protocol_id, fuente, records_identified=n,
                                       query=consulta_usada, year_from=year_from, year_to=year_to)
            except Exception as e:
                log.debug("No se pudo registrar la búsqueda de %s: %s", fuente, e)

        return {
            "status": "ok",
            "query": query,
            "total_matched": total_matched,
            "harvested_count": len(enriched_articles),
            "added_to_screening": added,
            "filtro_anios": (probe_res or {}).get("filtro_anios"),
            "fuentes_crudas": fuentes_crudas,
            "articles": enriched_articles,
        }
    finally:
        conn.close()


@router.post("/api/review/protocol/{protocol_id}/upload-audit")
async def upload_audit_endpoint(protocol_id: int, file: UploadFile = File(...)):
    """Audita de forma transparente un archivo CSV o RIS subido por el usuario sin insertarlo."""
    content = await file.read()
    if not content:
        raise HTTPException(400, "El archivo está vacío.")
    audit_res = importer.inspect_file(content, file.filename)
    return audit_res


@router.post("/api/review/protocol/{protocol_id}/upload-commit")
async def upload_commit_endpoint(
    protocol_id: int,
    file: UploadFile = File(...),
    source_label: str = Query("openalex", description="Etiqueta de base de datos de procedencia"),
):
    """Importa masivamente el archivo auditado al protocolo activo con persistencia segura."""
    content = await file.read()
    if not content:
        raise HTTPException(400, "El archivo está vacío.")
    conn = db.connect()
    try:
        protocol = db.get_protocol(conn, protocol_id)
        if not protocol:
            raise HTTPException(404, "Protocolo no encontrado")
        res = importer.import_csv_to_protocol(conn, protocol_id, content, file.filename, source_label=source_label)
        # La importación también es identificación (PRISMA ítem 6): se registra como una fuente.
        total = int(res.get("total_processed") or 0)
        if total:
            try:
                db.log_protocol_search(conn, protocol_id, f"importacion:{source_label}",
                                       records_identified=total,
                                       query=f"archivo:{file.filename}")
            except Exception as e:
                log.debug("No se pudo registrar la importación: %s", e)
        return res
    finally:
        conn.close()


@router.post("/api/review/protocol/{protocol_id}/enrich-article/{article_id}")
def enrich_article_endpoint(protocol_id: int, article_id: int):
    """Enriquece en segundo plano un artículo consultando OpenAlex por título para obtener DOI, revista y PDF."""
    conn = db.connect()
    try:
        return importer.enrich_article_from_openalex(conn, article_id)
    finally:
        conn.close()


@router.get("/api/review/protocol/{protocol_id}/screenings")
def list_screenings_endpoint(
    request: Request,
    protocol_id: int,
    decision: Optional[str] = Query(None, description="Filtrar por decisión: included, excluded, maybe, pending, not_retrieved"),
    stage: Optional[str] = Query(None, description="Filtrar por etapa: title_abstract, full_text"),
    limit: int = Query(200, ge=1, le=500),
    owner_id: Optional[str] = Query(None),
):
    """Lista las decisiones de screening de un protocolo."""
    user_id = _extract_owner_id(request, owner_id)
    conn = db.connect()
    try:
        screenings = db.list_screenings(conn, protocol_id, decision=decision, limit=limit,
                                        owner_id=user_id, stage=stage)
        return {"protocol_id": protocol_id, "total": len(screenings), "screenings": screenings}
    finally:
        conn.close()


@router.get("/api/review/protocol/{protocol_id}/flow-diagram")
def flow_diagram_endpoint(
    request: Request,
    protocol_id: int,
    owner_id: Optional[str] = Query(None),
):
    """Genera los conteos para el Diagrama de Flujo PRISMA-ScR (Identification → Screening → Included)."""
    user_id = _extract_owner_id(request, owner_id)
    conn = db.connect()
    try:
        flow = db.screening_flow_counts(conn, protocol_id, owner_id=user_id)
        protocol = db.get_protocol(conn, protocol_id, owner_id=user_id)
        if not protocol:
            raise HTTPException(404, "Protocolo no encontrado")
        flow["protocol_title"] = protocol.get("title")
        flow["protocol_status"] = protocol.get("status")
        # Trazabilidad de la estrategia (PRISMA ítem 6): cada búsqueda con su fuente y fecha.
        flow["busquedas"] = db.list_protocol_searches(conn, protocol_id, owner_id=user_id)
        return flow
    finally:
        conn.close()


@router.post("/api/review/protocol/{protocol_id}/screening/rank")
def active_learning_rank_endpoint(protocol_id: int, payload: dict = Body(default={})):
    """Reordena los candidatos de screening mediante Aprendizaje Activo Incremental (ASReview-like).

    Aprende de los artículos 'included' y 'excluded' ya decididos en el protocolo
    para proyectar un ranking que ahorra hasta un 80% de esfuerzo de lectura.
    """
    conn = db.connect()
    try:
        protocol = db.get_protocol(conn, protocol_id)
        if not protocol:
            raise HTTPException(404, "Protocolo no encontrado")

        # 1. Obtener decisiones previas
        screenings = db.list_screenings(conn, protocol_id, limit=1000)

        # 2. Artículos a clasificar: provistos en el payload o derivados del catálogo
        articles = payload.get("articles")
        if not articles:
            # Fallback: artículos del catálogo local que coincidan con la temática del protocolo
            query_str = f"{protocol.get('title') or ''} {protocol.get('research_question') or ''}"
            kws = parse_keywords(query_str)
            rows = conn.execute("SELECT * FROM articles ORDER BY cited_by DESC LIMIT 500").fetchall()
            all_arts = [db._row_to_article(r) for r in rows]
            if kws:
                articles = [a for a in all_arts if match_article(a, kws)["score"] > 0]
            else:
                articles = all_arts[:100]

        top_k = payload.get("limit", 100)
        alpha = float(payload.get("alpha", 1.0))
        beta = float(payload.get("beta", 0.45))

        learner = screening_ranker.ScreeningActiveLearner(alpha=alpha, beta=beta)
        ranked = learner.rank_candidates(articles, screenings, top_k=top_k)
        metrics = screening_ranker.compute_screening_progress_metrics(len(articles), screenings)

        return {
            "protocol_id": protocol_id,
            "metrics": metrics,
            "total_ranked": len(ranked),
            "candidates": ranked,
        }
    finally:
        conn.close()


@router.get("/api/review/protocol/{protocol_id}/screening/metrics")
def screening_metrics_endpoint(protocol_id: int):
    """Métricas de saturación y avance del screening PRISMA con Active Learning."""
    conn = db.connect()
    try:
        protocol = db.get_protocol(conn, protocol_id)
        if not protocol:
            raise HTTPException(404, "Protocolo no encontrado")
        screenings = db.list_screenings(conn, protocol_id, limit=2000)
        # Total estimado desde screening o catálogo
        total = db.screening_flow_counts(conn, protocol_id).get("total_screened", len(screenings))
        metrics = screening_ranker.compute_screening_progress_metrics(total, screenings)
        return {"protocol_id": protocol_id, "metrics": metrics}
    finally:
        conn.close()


@router.get("/api/review/protocol/{protocol_id}/prisma-checklist")
def prisma_checklist_endpoint(
    request: Request,
    protocol_id: int,
    owner_id: Optional[str] = Query(None),
):
    """Lista de verificación PRISMA 2020 (27 ítems) con estado y evidencia de cada uno."""
    user_id = _extract_owner_id(request, owner_id)
    conn = db.connect()
    try:
        if not db.get_protocol(conn, protocol_id, owner_id=user_id):
            raise HTTPException(404, "Protocolo no encontrado")
        from ... import prisma_report
        return prisma_report.build_checklist(conn, protocol_id, owner_id=user_id)
    finally:
        conn.close()


@router.get("/api/review/protocol/{protocol_id}/prisma-report")
def prisma_report_endpoint(
    request: Request,
    protocol_id: int,
    format: str = Query("md", pattern="^(md|json)$", description="md = informe Markdown; json = checklist"),
    owner_id: Optional[str] = Query(None),
):
    """Informe final de la revisión: protocolo, búsquedas, flujo PRISMA 2020 y checklist."""
    user_id = _extract_owner_id(request, owner_id)
    conn = db.connect()
    try:
        if not db.get_protocol(conn, protocol_id, owner_id=user_id):
            raise HTTPException(404, "Protocolo no encontrado")
        from ... import prisma_report
        if format == "json":
            return {"status": "ok", "checklist": prisma_report.build_checklist(conn, protocol_id, owner_id=user_id)}
        informe = prisma_report.build_report(conn, protocol_id, owner_id=user_id)
        return Response(
            content=informe,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=informe_prisma_{protocol_id}.md"},
        )
    finally:
        conn.close()

