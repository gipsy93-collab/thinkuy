"""Subrouter de la API de Thinkuy."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile

from ... import config, db, text_extractor
from ...harvester import abstract_chain
from ..common import (
    _as_int,
)

router = APIRouter(tags=['fulltext'])
log = logging.getLogger('radar.api.fulltext')

def _resolver_con_render(url: str, previo: dict, client: httpx.Client) -> dict:
    """Escalón 5: renderiza la URL y vuelve a aplicar la cadena sobre el HTML renderizado.

    Devuelve el resultado del escalón 2 tal cual si el render no está disponible, si
    `robots.txt` lo prohíbe o si tampoco aporta el resumen — siempre declarando el motivo.
    """
    from ...harvester import render_js

    if not render_js.disponible():
        previo["render_js"] = {"usado": False, "detalle": "Playwright no está instalado"}
        return previo
    try:
        html_render, de_cache = render_js.render_cacheado(url, http=client)
    except render_js.RobotsDenegado as e:
        previo["render_js"] = {"usado": False, "detalle": str(e)}
        return previo
    except Exception as e:
        previo["render_js"] = {"usado": False, "detalle": f"{type(e).__name__}: {e}"[:160]}
        return previo

    etiquetas = abstract_chain.metas(html_render)
    segundo = abstract_chain.resolve_abstract(
        html_render, http=client,
        allow_pdf=False,  # el PDF ya se intentó en el escalón 2
        titulo=etiquetas.get("citation_title", ""),
        idioma=etiquetas.get("citation_language", ""),
    )
    telemetria = {"usado": True, "de_cache": de_cache, "bytes_render": len(html_render.encode("utf-8")),
                  "detalle": segundo["detalle"][:160]}
    if segundo["resumen"]:
        segundo["escalon"] = 5
        segundo["render_js"] = telemetria
        segundo["detalle"] = f"localizado tras renderizar la página ({segundo['fuente']})"
        return segundo
    previo["render_js"] = telemetria
    return previo


@router.post("/api/fulltext")
def save_fulltext_endpoint(payload: dict = Body(...)):
    """Guarda el texto completo estructurado (Markdown / Secciones) de un artículo."""
    doi = payload.get("doi")
    markdown_text = payload.get("markdown_text")
    if not doi or not markdown_text:
        raise HTTPException(400, "Campos 'doi' y 'markdown_text' son requeridos")
    conn = db.connect()
    try:
        db.save_article_fulltext(
            conn,
            doi=doi,
            markdown_text=markdown_text,
            sections=payload.get("sections"),
            word_count=payload.get("word_count"),
            page_count=payload.get("page_count"),
        )
        return {"status": "ok", "doi": doi}
    finally:
        conn.close()


@router.get("/api/fulltext/{doi:path}")
def get_fulltext_endpoint(doi: str):
    """Recupera el texto completo almacenado de un artículo."""
    conn = db.connect()
    try:
        ft = db.get_article_fulltext(conn, doi)
        if not ft:
            raise HTTPException(404, f"Texto completo no disponible para DOI: {doi}")
        return ft
    finally:
        conn.close()


@router.post("/api/fulltext/extract-pdf")
async def extract_pdf_endpoint(
    file: UploadFile = File(..., description="Archivo PDF del paper"),
    doi: Optional[str] = Query(None, description="DOI del manuscrito"),
    cited_dois: Optional[List[str]] = Query(None, description="DOIs citados a buscar en el texto"),
):
    """Convierte un PDF a Markdown estructurado y extrae contextos de citación cualitativa."""
    import tempfile

    suffix = Path(file.filename or "paper.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        extracted = text_extractor.extract_paper_to_markdown(tmp_path)
        if not extracted:
            raise HTTPException(500, "Error extrayendo texto del PDF o PyMuPDF no disponible")

        resolved_doi = (doi or (file.filename or "").replace(".pdf", "")).strip().lower()

        conn = db.connect()
        try:
            res = text_extractor.ingest_fulltext_and_contexts(
                conn,
                citing_doi=resolved_doi,
                full_text=extracted["full_text"],
                sections=extracted.get("sections"),
                word_count=extracted.get("word_count"),
                page_count=extracted.get("page_count"),
                cited_dois=list(cited_dois or []) or None,
                references_texts=extracted.get("references"),
                http=None,
                auto_ingest_refs=True,
            )
            return {
                "status": "ok",
                "doi": resolved_doi,
                "word_count": extracted.get("word_count"),
                "page_count": extracted.get("page_count"),
                "sections_found": list(extracted.get("sections", {}).keys()),
                "references_count": len(extracted.get("references", [])),
                "citation_contexts_extracted": res["citation_contexts_extracted"],
                "by_function": res["by_function"],
                "ingested_cited": res["ingested_cited"],
                "contexts": res["contexts"],
            }
        finally:
            conn.close()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.post("/api/citation-context")
def save_citation_context_endpoint(payload: dict = Body(...)):
    """Almacena el párrafo/oración de contexto donde el Autor A cita al Autor B."""
    citing_doi = payload.get("citing_doi")
    cited_doi = payload.get("cited_doi")
    if not citing_doi or not cited_doi:
        raise HTTPException(400, "Campos 'citing_doi' y 'cited_doi' son requeridos")
    conn = db.connect()
    try:
        cid = db.save_citation_context(conn, citing_doi=citing_doi, cited_doi=cited_doi, context=payload)
        return {"status": "ok", "context_id": cid}
    finally:
        conn.close()


@router.get("/api/citation-contexts")
def get_citation_contexts_endpoint(
    citing_doi: Optional[str] = Query(None),
    cited_doi: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None, description="Filtra por estado de validación: pending, validated, corrected, rejected"),
):
    """Consulta contextos de citación registrados."""
    conn = db.connect()
    try:
        contexts = db.get_citation_contexts(conn, citing_doi=citing_doi, cited_doi=cited_doi, limit=limit, status=status)
        return {"count": len(contexts), "contexts": contexts}
    finally:
        conn.close()


@router.post("/api/citation-contexts/{context_id}/validate")
def validate_context_endpoint(context_id: int, payload: dict = Body(...)):
    """Validación humana de un contexto: validated / corrected / rejected / pending."""
    conn = db.connect()
    try:
        try:
            updated = db.validate_citation_context(
                conn,
                context_id,
                payload.get("decision"),
                corrected_function=payload.get("corrected_function"),
                corrected_claim=payload.get("corrected_claim"),
                by_=str(payload.get("by") or "researcher"),
            )
        except ValueError as e:
            raise HTTPException(422, str(e))
        if not updated:
            raise HTTPException(404, "Contexto no encontrado")
        return {"status": "ok", "context": updated}
    finally:
        conn.close()


@router.post("/api/fulltext/backfill")
def fulltext_backfill_endpoint(payload: dict = Body(default={})):
    """Rellena textos completos por la vía automática legal (Europe PMC, XML JATS).

    Cubre literatura **biomédica** indexada en PMC. Para el diamante iberoamericano
    (SciELO/Redalyc/OJS) use `POST /api/fulltext/fetch-oa/{doi}`, que resuelve el PDF
    abierto vía Unpaywall.
    """
    limite = _as_int(payload.get("limit"), default=10, minimum=1, maximum=100)
    from ...harvester import fulltext_auto
    conn = db.connect()
    try:
        client = httpx.Client(headers={"User-Agent": config.USER_AGENT},
                              follow_redirects=True, timeout=45.0)
        try:
            res = fulltext_auto.backfill_fulltexts(conn, http=client, limit=limite)
        finally:
            client.close()
        return {"status": "ok", **res}
    finally:
        conn.close()


@router.post("/api/fulltext/fetch-oa/{doi:path}")
def fulltext_fetch_oa_endpoint(
    doi: str,
    force: bool = Query(False, description="Re-descargar aunque ya exista texto completo"),
):
    """Descarga el PDF de ACCESO ABIERTO de un DOI y lo ingesta.

    Escalera **medida** (sonda 22-09-2026, 85% de cobertura sobre muestra aleatoria iberoamericana):
    Unpaywall `url_for_pdf` y, si falla, DOI -> `citation_pdf_url` de la ficha del editor.

    Regla legal: **solo se descarga cuando la fuente declara acceso abierto** (Unpaywall `is_oa`
    o plataforma de acceso abierto conocida: SciELO/Redalyc). Se consulta `robots.txt` y se valida
    que el cuerpo sea un PDF real. Es una acción explícita del investigador, no un raspado masivo.
    """
    import tempfile
    from pathlib import Path as _Path


    doi = (doi or "").strip().lower()
    if not doi:
        raise HTTPException(422, "doi es obligatorio")
    conn = db.connect()
    try:
        if not force and db.get_article_fulltext(conn, doi):
            return {"status": "ya_existe", "doi": doi}
        client = httpx.Client(headers={"User-Agent": config.USER_AGENT},
                              follow_redirects=True, timeout=60.0)
        try:
            from ...harvester import fulltext_oa
            resol = fulltext_oa.resolve_pdf(client, doi)
            body = resol.get("body")
            pdf_url = resol.get("pdf_url")
            if not body:
                return {"status": "sin_oa", "doi": doi, "motivo": resol.get("motivo") or "sin_pdf",
                        "ruta": resol.get("ruta"),
                        "detalle": "Ninguna ruta de acceso abierto entregó un PDF"}
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(body)
                tmp_path = tmp.name
            try:
                extracted = text_extractor.extract_paper_to_markdown(tmp_path)
            finally:
                try:
                    _Path(tmp_path).unlink()
                except Exception:
                    pass
            if not extracted:
                return {"status": "extraccion_fallida", "doi": doi, "url": pdf_url}
            res = text_extractor.ingest_fulltext_and_contexts(
                conn,
                citing_doi=doi,
                full_text=extracted["full_text"],
                sections=extracted.get("sections"),
                word_count=extracted.get("word_count"),
                page_count=extracted.get("page_count"),
                cited_dois=None,
                references_texts=extracted.get("references"),
                http=client,
                auto_ingest_refs=True,
            )
            return {
                "status": "ok",
                "doi": doi,
                "ruta": resol.get("ruta"),
                "oa_status": resol.get("oa_status"),
                "host_type": resol.get("host_type"),
                "pdf_url": pdf_url,
                "secciones": list((extracted.get("sections") or {}).keys()),
                "words": extracted.get("word_count"),
                "contextos_de_cita": res.get("citation_contexts_extracted"),
                "citados_ingeridos": len(res.get("ingested_cited") or []),
            }
        finally:
            client.close()
    finally:
        conn.close()


@router.post("/api/metadata/abstract")
def metadata_abstract_endpoint(payload: dict = Body(default={})):
    """Resuelve el resumen de una ficha por la **cadena determinista** (Hito 38). Sin modelo.

    Orden de la cadena: `citation_abstract` -> `DC.Description` (OJS) -> `citation_pdf_url`
    (sección abstract del PDF) -> `description`. Si ninguna fuente lo trae, devuelve el campo
    **vacío** con el motivo declarado.

    Regla que sostiene el diseño: **ningún modelo rellena este campo**. Se midió que un SLM
    fabrica resúmenes plausibles cuando la fuente no los contiene (6 de 7 fichas de Redalyc
    cuyo PDF tampoco trae resumen), y eso contamina cribado y charting.

    Entrada: `{"url": "..."}` para descargar la ficha, o `{"html": "..."}` si ya se tiene.
    Opcional: `titulo`, `idioma`, `allow_pdf` (False evita descargar el PDF),
    `render_js` (escalón 5, ver abajo).

    **Escalón 5 (`render_js: true`)**: si la cadena no encuentra el resumen y la ficha es
    dependiente de JavaScript, se renderiza con navegador sin cabeza, se respeta
    `robots.txt` y el HTML queda en caché. Es **opt-in y por URL concreta**, nunca por
    defecto. Aviso de honestidad: a 18-09-2026 **no hay ningún caso medido que lo requiera**
    —el 403 de `old.scielo.br` es del servidor (Googlebot también lo recibe) y el resumen de
    Redalyc, cuando existe, está en el registro OAI— de modo que hoy es último recurso
    disponible, no una necesidad demostrada.
    """

    url = str(payload.get("url") or "").strip()
    html = payload.get("html") or ""
    titulo = str(payload.get("titulo") or "")
    idioma = str(payload.get("idioma") or "")
    allow_pdf = bool(payload.get("allow_pdf", True))
    render_js = bool(payload.get("render_js", False))

    if not url and not html:
        raise HTTPException(422, "se requiere 'url' o 'html'")

    client = httpx.Client(headers={"User-Agent": config.USER_AGENT},
                          follow_redirects=True, timeout=60.0)
    try:
        if not html:
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except Exception as e:
                return {"status": "descarga_fallida", "url": url,
                        "detalle": f"{type(e).__name__}: la ficha no se pudo descargar"}
            html = resp.text
        etiquetas = abstract_chain.metas(html)
        resultado = abstract_chain.resolve_abstract(
            html, http=client,
            allow_pdf=allow_pdf,
            titulo=titulo or etiquetas.get("citation_title", ""),
            idioma=idioma or etiquetas.get("citation_language", ""),
        )
        resultado["escalon"] = 2

        if render_js and not resultado["resumen"] and url:
            resultado = _resolver_con_render(url, resultado, client)

        return {"status": "ok" if resultado["resumen"] else "sin_resumen",
                "url": url, "bytes_ficha": len(html.encode("utf-8")), **resultado}
    finally:
        client.close()


@router.post("/api/fulltext/backfill-auto")
def fulltext_backfill_auto_endpoint(payload: dict = Body(default={})):
    """Auto-ingesta integral de textos completos (Europe PMC XML + PDFs de Acceso Abierto vía Unpaywall).

    Sigue la Escalera de Ingesta y respeta el acceso abierto legal.
    Puede ejecutarse sobre todo el catálogo o acotarse a los artículos incluidos de un protocolo PRISMA.
    """
    import tempfile
    from pathlib import Path as _Path

    from ...harvester import fulltext_auto

    protocol_id = payload.get("protocol_id")
    limit = _as_int(payload.get("limit"), default=10, minimum=1, maximum=50)

    conn = db.connect()
    try:
        if protocol_id:
            screenings = db.list_screenings(conn, int(protocol_id), decision="included")
            dois = [s["doi"].strip().lower() for s in screenings if s.get("doi")]
            if not dois:
                return {
                    "status": "ok",
                    "total_evaluados": 0,
                    "recuperados_pmc": 0,
                    "recuperados_oa_pdf": 0,
                    "sin_oa": 0,
                    "detalles": [],
                }
            placeholders = ",".join(["?"] * len(dois))
            sql = f"""
                SELECT a.* FROM articles a
                LEFT JOIN article_fulltext f ON LOWER(f.doi) = LOWER(a.doi)
                WHERE f.doi IS NULL AND a.doi IN ({placeholders})
                LIMIT ?
            """
            rows = conn.execute(sql, (*dois, limit)).fetchall()
        else:
            sql = """
                SELECT a.* FROM articles a
                LEFT JOIN article_fulltext f ON LOWER(f.doi) = LOWER(a.doi)
                WHERE f.doi IS NULL AND a.doi IS NOT NULL
                ORDER BY (a.source = 'europepmc') DESC, COALESCE(a.cited_by, 0) DESC
                LIMIT ?
            """
            rows = conn.execute(sql, (limit,)).fetchall()

        candidatos = [db._row_to_article(r) for r in rows]
        client = httpx.Client(
            headers={"User-Agent": config.USER_AGENT},
            follow_redirects=True,
            timeout=45.0,
        )

        recuperados_pmc = 0
        recuperados_oa_pdf = 0
        sin_oa = 0
        detalles = []

        try:
            for art in candidatos:
                doi = (art.get("doi") or "").strip().lower()
                if not doi:
                    continue

                if db.get_article_fulltext(conn, doi):
                    detalles.append({"doi": doi, "status": "ya_existe"})
                    continue

                # Escalón A: Intentar vía Europe PMC (XML JATS limpio y estructurado)
                res_pmc = None
                try:
                    res_pmc = fulltext_auto.ingest_one(conn, client, art)
                except Exception as e:
                    log.warning("backfill-auto Europe PMC fallo para %s: %s", doi, e)

                if res_pmc and not res_pmc.get("skipped"):
                    recuperados_pmc += 1
                    detalles.append({"doi": doi, "status": "ok", "fuente": "europepmc_xml"})
                    continue

                # Escalón B: PDF de acceso abierto por la escalera medida
                # (Unpaywall -> DOI citation_pdf_url; sonda 22-09-2026, 85% iberoamericano).
                try:
                    from ...harvester import fulltext_oa
                    resol = fulltext_oa.resolve_pdf(client, doi)
                    body = resol.get("body")
                    if body:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                            tmp.write(body)
                            tmp_path = tmp.name
                        try:
                            extracted = text_extractor.extract_paper_to_markdown(tmp_path)
                        finally:
                            try:
                                _Path(tmp_path).unlink()
                            except Exception:
                                pass
                        if extracted and extracted.get("full_text"):
                            text_extractor.ingest_fulltext_and_contexts(
                                conn,
                                citing_doi=doi,
                                full_text=extracted["full_text"],
                                sections=extracted.get("sections"),
                                word_count=extracted.get("word_count"),
                                page_count=extracted.get("page_count"),
                                cited_dois=None,
                                references_texts=extracted.get("references"),
                                http=client,
                                auto_ingest_refs=True,
                            )
                            recuperados_oa_pdf += 1
                            detalles.append({
                                "doi": doi,
                                "status": "ok",
                                "fuente": f"oa_pdf:{resol.get('ruta')}",
                                "oa_status": resol.get("oa_status"),
                            })
                            continue
                except Exception as e:
                    log.warning("backfill-auto OA fallo para %s: %s", doi, e)

                sin_oa += 1
                detalles.append({"doi": doi, "status": "sin_oa"})

        finally:
            client.close()

        return {
            "status": "ok",
            "total_evaluados": len(candidatos),
            "recuperados_pmc": recuperados_pmc,
            "recuperados_oa_pdf": recuperados_oa_pdf,
            "sin_oa": sin_oa,
            "detalles": detalles,
        }
    finally:
        conn.close()


