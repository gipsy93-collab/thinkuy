"""Subrouter de la API de Thinkuy."""
from __future__ import annotations

import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Request, Response

from ... import charting, citation_graph, config, db
from ..common import (
    _as_int,
    _extract_owner_id,
)

router = APIRouter(tags=['charting'])
log = logging.getLogger('radar.api.charting')

@router.post("/api/review/protocol/{protocol_id}/chart")
def save_charting_endpoint(request: Request, protocol_id: int, payload: dict = Body(...)):
    """Guarda o actualiza los datos de charteo (extracción estructurada PCC) de un artículo."""
    doi = payload.get("doi")
    if not doi:
        raise HTTPException(400, "El campo 'doi' es obligatorio")
    user_id = _extract_owner_id(request, payload.get("owner_id"))
    conn = db.connect()
    try:
        result = db.save_charting(
            conn, protocol_id,
            doi=doi,
            data=payload,
            article_id=payload.get("article_id"),
            owner_id=user_id,
        )
        return {"status": "ok", "charting": result}
    finally:
        conn.close()


@router.post("/api/review/protocol/{protocol_id}/hydrate-abstracts")
def hydrate_abstracts_endpoint(protocol_id: int, payload: dict = Body(default={})):
    """Completa los resúmenes que faltan en los artículos **incluidos** de un protocolo.

    Prueba, en orden: la ficha por DOI (OpenAlex → Crossref) y la página declarada (cadena
    determinista). **Declara lo que no consigue y por qué** — hay resúmenes que sencillamente no
    existen en fuentes abiertas (editoriales de pago) y otros que están tras un bloqueo de la
    fuente (Dialnet responde 503 a nuestras peticiones). Esos se leen en el texto completo;
    **no se inventan**.

    Es una acción explícita del investigador, así que sí escribe en el catálogo.
    """
    from ...harvester import hidratar

    limite = _as_int(payload.get("limit"), default=200, minimum=1, maximum=500)
    conn = db.connect()
    try:
        client = httpx.Client(headers={"User-Agent": config.USER_AGENT},
                              follow_redirects=True, timeout=45.0)
        try:
            informe = hidratar.hidratar_resumenes(conn, protocol_id, http=client, limite=limite)
        finally:
            client.close()
        return {"status": "ok", "protocol_id": protocol_id, **informe}
    finally:
        conn.close()


@router.post("/api/review/protocol/{protocol_id}/chart-propose")
def chart_propose_endpoint(protocol_id: int, payload: dict = Body(...)):
    """Propone los campos PCC/PICC de una ficha a partir de su resumen. **El humano verifica.**

    El motor nunca inventa: cada valor propuesto debe aparecer **literalmente** en la fuente o se
    descarta declarando el motivo (`backend/radar/charting.py`). Devuelve también los campos que
    se descartaron y por qué, para que la revisión sea auditable.

    Entrada: `{"doi": "...", "title": "...", "abstract": "...", "keywords": [...]}`.
    Con `use_model: false` se usa solo la extracción determinista (resúmenes estructurados).
    """

    resumen = str(payload.get("abstract") or "").strip()
    titulo = str(payload.get("title") or "").strip()
    palabras = payload.get("keywords") or []
    usar_modelo = bool(payload.get("use_model", True))

    resultado = charting.proponer_pcc(titulo=titulo, resumen=resumen, palabras_clave=palabras,
                                      usar_modelo=usar_modelo)
    return {"status": "ok" if resultado["campos"] else "sin_propuesta",
            "doi": str(payload.get("doi") or ""), **resultado}


@router.get("/api/review/protocol/{protocol_id}/charting")
def list_charting_endpoint(
    request: Request,
    protocol_id: int,
    limit: int = Query(200, ge=1, le=500),
    owner_id: Optional[str] = Query(None),
):
    """Lista los datos de charteo de un protocolo."""
    user_id = _extract_owner_id(request, owner_id)
    conn = db.connect()
    try:
        entries = db.list_charting(conn, protocol_id, limit=limit, owner_id=user_id)
        return {"protocol_id": protocol_id, "total": len(entries), "charting": entries}
    finally:
        conn.close()


@router.get("/api/review/protocol/{protocol_id}/export")
def export_protocol_endpoint(
    request: Request,
    protocol_id: int,
    format: str = Query("csv", pattern="^(csv|ris|bibtex)$", description="Formato de exportación"),
    decision: Optional[str] = Query("included", description="Filtro de decisión (included, excluded, all)"),
    owner_id: Optional[str] = Query(None),
):
    """Exporta los artículos de un protocolo en formato RIS, BibTeX o CSV."""
    user_id = _extract_owner_id(request, owner_id)
    conn = db.connect()
    try:
        decision_filter = decision if decision != "all" else None
        articles = db.export_protocol_articles(conn, protocol_id, decision_filter=decision_filter, owner_id=user_id)
        if not articles and decision == "included":
            articles = db.export_protocol_articles(conn, protocol_id, decision_filter=None, owner_id=user_id)
        protocol = db.get_protocol(conn, protocol_id, owner_id=user_id)
        if not protocol:
            raise HTTPException(404, "Protocolo no encontrado")

        if format == "ris":
            lines = []
            for a in articles:
                lines.append("TY  - JOUR")
                if a.get("title"):
                    lines.append(f"TI  - {a['title']}")
                if a.get("doi"):
                    lines.append(f"DO  - {a['doi']}")
                if a.get("year"):
                    lines.append(f"PY  - {a['year']}")
                if a.get("journal_title"):
                    lines.append(f"JO  - {a['journal_title']}")
                if a.get("abstract"):
                    lines.append(f"AB  - {a['abstract']}")
                authors = a.get("authors")
                if isinstance(authors, str):
                    try:
                        authors = json.loads(authors)
                    except Exception:
                        authors = []
                for auth in (authors or []):
                    name = auth.get("name") if isinstance(auth, dict) else str(auth)
                    if name:
                        lines.append(f"AU  - {name}")
                if a.get("charting"):
                    c = a["charting"]
                    if c.get("key_findings"):
                        lines.append(f"N1  - Key Findings: {c['key_findings']}")
                lines.append("ER  - ")
                lines.append("")
            content = "\n".join(lines)
            return Response(
                content=content,
                media_type="application/x-research-info-systems",
                headers={"Content-Disposition": f"attachment; filename=thinkuy_protocol_{protocol_id}.ris"},
            )

        elif format == "bibtex":
            entries = []
            for i, a in enumerate(articles):
                key = (a.get("doi") or f"art{i+1}").replace("/", "_").replace(".", "_")
                entry = f"@article{{{key},\n"
                if a.get("title"):
                    entry += f"  title = {{{a['title']}}},\n"
                if a.get("year"):
                    entry += f"  year = {{{a['year']}}},\n"
                if a.get("journal_title"):
                    entry += f"  journal = {{{a['journal_title']}}},\n"
                if a.get("doi"):
                    entry += f"  doi = {{{a['doi']}}},\n"
                if a.get("abstract"):
                    entry += f"  abstract = {{{a['abstract'][:500]}}},\n"
                authors = a.get("authors")
                if isinstance(authors, str):
                    try:
                        authors = json.loads(authors)
                    except Exception:
                        authors = []
                if authors:
                    names = []
                    for auth in authors:
                        name = auth.get("name") if isinstance(auth, dict) else str(auth)
                        if name:
                            names.append(name)
                    if names:
                        entry += f"  author = {{{' and '.join(names)}}},\n"
                entry += "}"
                entries.append(entry)
            content = "\n\n".join(entries)
            return Response(
                content=content,
                media_type="application/x-bibtex",
                headers={"Content-Disposition": f"attachment; filename=thinkuy_protocol_{protocol_id}.bib"},
            )

        else:  # CSV
            import csv
            import io
            output = io.StringIO()
            writer = csv.writer(output)
            headers = ["DOI", "Title", "Year", "Journal", "Cited By", "Role", "Population", "Concept", "Context", "Methodology", "Key Findings", "Limitations", "Quality Score", "Notes"]
            writer.writerow(headers)
            for a in articles:
                c = a.get("charting", {}) or {}
                role = ""
                try:
                    role = citation_graph.classify_epistemic_role(a)
                except Exception:
                    pass
                writer.writerow([
                    a.get("doi", ""),
                    a.get("title", ""),
                    a.get("year", ""),
                    a.get("journal_title", ""),
                    a.get("cited_by", 0),
                    role,
                    c.get("population", ""),
                    c.get("concept", ""),
                    c.get("context", ""),
                    c.get("methodology", ""),
                    c.get("key_findings", ""),
                    c.get("limitations", ""),
                    c.get("quality_score", ""),
                    c.get("notes", ""),
                ])
            content = output.getvalue()
            return Response(
                content=content,
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=thinkuy_protocol_{protocol_id}.csv"},
            )
    finally:
        conn.close()

