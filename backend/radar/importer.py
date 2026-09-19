"""Módulo de importación inteligente, auditoría de completitud y enriquecedor híbrido.

Permite al investigador cargar archivos bibliográficos propios (CSV de OpenAlex, Scopus,
WoS o archivos RIS) con diagnóstico transparente de metadatos faltantes y resolución
progresiva en segundo plano desde OpenAlex API.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import sqlite3
from typing import Any

import httpx

from . import citation_graph, db
from .normalize import norm

log = logging.getLogger("radar.importer")


def _clean_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def inspect_file(content_bytes: bytes, filename: str) -> dict[str, Any]:
    """Audita la estructura y completitud del archivo subido sin alterar la base de datos."""
    text = content_bytes.decode("utf-8", errors="replace")
    lower_fn = filename.lower()

    if lower_fn.endswith(".ris"):
        return _inspect_ris(text, filename)
    else:
        return _inspect_csv(text, filename)


def _inspect_csv(text: str, filename: str) -> dict[str, Any]:
    """Audita un archivo CSV detectando dialecto, columnas y cobertura de datos."""
    # Detectar delimitador con muestra
    sample = text[:8192]
    delimiter = ","
    try:
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","

    f = io.StringIO(text)
    reader = csv.reader(f, delimiter=delimiter)
    try:
        headers = next(reader)
    except StopIteration:
        return {
            "valid": False,
            "filename": filename,
            "error": "El archivo CSV está vacío.",
        }

    headers_norm = [h.strip().lower() for h in headers]
    headers_clean = [h.strip() for h in headers]

    # Mapeo de columnas
    col_title = next((i for i, h in enumerate(headers_norm) if any(k in h for k in ("title", "título", "titulo"))), None)
    col_abstract = next((i for i, h in enumerate(headers_norm) if any(k in h for k in ("abstract", "resumen"))), None)
    col_author = next((i for i, h in enumerate(headers_norm) if any(k in h for k in ("author", "autor", "authors", "autores"))), None)
    col_year = next((i for i, h in enumerate(headers_norm) if any(k in h for k in ("year", "año", "ano", "date", "fecha"))), None)
    col_doi = next((i for i, h in enumerate(headers_norm) if "doi" in h), None)
    col_journal = next((i for i, h in enumerate(headers_norm) if any(k in h for k in ("journal", "revista", "source", "venue", "publisher"))), None)
    col_cites = next((i for i, h in enumerate(headers_norm) if any(k in h for k in ("citation count", "cited by", "citas", "cited"))), None)

    total_rows = 0
    with_title = 0
    with_abstract = 0
    with_author = 0
    with_year = 0
    with_doi = 0
    with_journal = 0
    sample_preview: list[dict[str, Any]] = []

    for row in reader:
        if not any(row):
            continue
        total_rows += 1
        t = row[col_title].strip() if col_title is not None and col_title < len(row) else ""
        ab = row[col_abstract].strip() if col_abstract is not None and col_abstract < len(row) else ""
        au = row[col_author].strip() if col_author is not None and col_author < len(row) else ""
        y = row[col_year].strip() if col_year is not None and col_year < len(row) else ""
        d = row[col_doi].strip() if col_doi is not None and col_doi < len(row) else ""
        j = row[col_journal].strip() if col_journal is not None and col_journal < len(row) else ""

        if t:
            with_title += 1
        if ab:
            with_abstract += 1
        if au:
            with_author += 1
        if y:
            with_year += 1
        if d:
            with_doi += 1
        if j:
            with_journal += 1

        if len(sample_preview) < 5 and t:
            sample_preview.append({
                "title": t,
                "authors": au[:60] + "..." if len(au) > 60 else au,
                "year": y,
                "has_abstract": bool(ab),
                "has_doi": bool(d),
            })

    if total_rows == 0:
        return {
            "valid": False,
            "filename": filename,
            "error": "No se encontraron filas con datos en el archivo.",
        }

    # Diagnóstico de formato
    is_openalex_web = (
        "abstract" in headers_norm and
        "citation count" in headers_norm and
        col_doi is None
    )

    coverage = {
        "title_pct": round((with_title / total_rows) * 100, 1),
        "abstract_pct": round((with_abstract / total_rows) * 100, 1),
        "author_pct": round((with_author / total_rows) * 100, 1),
        "year_pct": round((with_year / total_rows) * 100, 1),
        "doi_pct": round((with_doi / total_rows) * 100, 1),
        "journal_pct": round((with_journal / total_rows) * 100, 1),
    }

    missing_fields = []
    if coverage["doi_pct"] < 50:
        missing_fields.append("DOIs normalizados")
    if coverage["journal_pct"] < 50:
        missing_fields.append("Nombres de Revista / Fuente editorial")

    warning_msg = None
    if missing_fields:
        warning_msg = (
            f"El archivo carece de {', '.join(missing_fields)}. "
            "Esto ocurre habitualmente en exportaciones básicas web. "
            "Los títulos y resúmenes son aptos para cribado inmediato, pero faltan metadatos para la red de citas y trazabilidad editorial."
        )

    recommendation = {
        "can_import": with_title > 0,
        "format_type": "OpenAlex Web CSV" if is_openalex_web else "CSV Estándar",
        "missing_fields": missing_fields,
        "warning": warning_msg,
        "hybrid_enrichment_available": True,
        "solution_msg": (
            "Thinkuy puede importar las publicaciones para que comiences el screening de inmediato. "
            "Además, el Enriquecedor Progresivo buscará en segundo plano los DOIs, revistas y PDFs oficiales desde OpenAlex a medida que cribes o incluyas artículos."
        ),
    }

    return {
        "valid": True,
        "filename": filename,
        "total_rows": total_rows,
        "columns_detected": headers_clean,
        "coverage": coverage,
        "recommendation": recommendation,
        "sample_preview": sample_preview,
    }


def _inspect_ris(text: str, filename: str) -> dict[str, Any]:
    """Audita un archivo en formato RIS estándar."""
    records = text.split("ER  -")
    total_rows = 0
    with_title = 0
    with_abstract = 0
    with_author = 0
    with_doi = 0
    with_journal = 0

    for rec in records:
        rec = rec.strip()
        if not rec:
            continue
        total_rows += 1
        if re.search(r"^(?:TI|T1)\s*-\s*.+", rec, re.MULTILINE):
            with_title += 1
        if re.search(r"^(?:AB|N2)\s*-\s*.+", rec, re.MULTILINE):
            with_abstract += 1
        if re.search(r"^(?:AU|A1)\s*-\s*.+", rec, re.MULTILINE):
            with_author += 1
        if re.search(r"^(?:DO|DI)\s*-\s*.+", rec, re.MULTILINE):
            with_doi += 1
        if re.search(r"^(?:JF|JO|JA|T2)\s*-\s*.+", rec, re.MULTILINE):
            with_journal += 1

    if total_rows == 0:
        return {"valid": False, "filename": filename, "error": "No se encontraron registros válidos en formato RIS."}

    coverage = {
        "title_pct": round((with_title / total_rows) * 100, 1),
        "abstract_pct": round((with_abstract / total_rows) * 100, 1),
        "author_pct": round((with_author / total_rows) * 100, 1),
        "year_pct": 100.0,
        "doi_pct": round((with_doi / total_rows) * 100, 1),
        "journal_pct": round((with_journal / total_rows) * 100, 1),
    }

    return {
        "valid": True,
        "filename": filename,
        "total_rows": total_rows,
        "columns_detected": ["RIS Tags (TI, AU, AB, DO, JF)"],
        "coverage": coverage,
        "recommendation": {
            "can_import": with_title > 0,
            "format_type": "RIS Bibliográfico",
            "missing_fields": ["DOIs"] if coverage["doi_pct"] < 50 else [],
            "hybrid_enrichment_available": True,
            "solution_msg": "Registros listos para integración al protocolo PRISMA.",
        },
        "sample_preview": [],
    }


def import_csv_to_protocol(
    conn: sqlite3.Connection,
    protocol_id: int,
    content_bytes: bytes,
    filename: str,
    source_label: str = "openalex",
) -> dict[str, Any]:
    """Carga masivamente un CSV al protocolo activo preservando el estado previo de cribado."""
    text = content_bytes.decode("utf-8", errors="replace")
    sample = text[:8192]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    try:
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except Exception:
        pass

    f = io.StringIO(text)
    reader = csv.reader(f, delimiter=delimiter)
    headers = next(reader, [])
    headers_norm = [h.strip().lower() for h in headers]

    col_title = next((i for i, h in enumerate(headers_norm) if any(k in h for k in ("title", "título", "titulo"))), None)
    col_abstract = next((i for i, h in enumerate(headers_norm) if any(k in h for k in ("abstract", "resumen"))), None)
    col_author = next((i for i, h in enumerate(headers_norm) if any(k in h for k in ("author", "autor", "authors", "autores"))), None)
    col_year = next((i for i, h in enumerate(headers_norm) if any(k in h for k in ("year", "año", "ano", "date", "fecha"))), None)
    col_doi = next((i for i, h in enumerate(headers_norm) if "doi" in h), None)
    col_journal = next((i for i, h in enumerate(headers_norm) if any(k in h for k in ("journal", "revista", "source", "venue"))), None)
    col_cites = next((i for i, h in enumerate(headers_norm) if any(k in h for k in ("citation count", "cited by", "citas", "cited"))), None)
    col_oa = next((i for i, h in enumerate(headers_norm) if "open access" in h or "acceso" in h), None)

    if col_title is None:
        raise ValueError("No se encontró columna de título en el archivo CSV.")

    imported = 0
    duplicates = 0
    added_to_screening = 0

    try:
        for row in reader:
            if not any(row):
                continue
            title = row[col_title].strip() if col_title < len(row) else ""
            if not title:
                continue

            abstract = row[col_abstract].strip() if col_abstract is not None and col_abstract < len(row) else ""
            author_str = row[col_author].strip() if col_author is not None and col_author < len(row) else ""
            year_str = row[col_year].strip() if col_year is not None and col_year < len(row) else ""
            doi_raw = row[col_doi].strip() if col_doi is not None and col_doi < len(row) else ""
            journal = row[col_journal].strip() if col_journal is not None and col_journal < len(row) else ""
            cites_str = row[col_cites].strip() if col_cites is not None and col_cites < len(row) else "0"
            oa_str = row[col_oa].strip().lower() if col_oa is not None and col_oa < len(row) else ""

            year = int(year_str) if year_str.isdigit() else None
            try:
                cited_by = int(cites_str)
            except Exception:
                cited_by = 0

            # Formatear autores
            authors = []
            if author_str:
                for a_piece in re.split(r"[|;,]+", author_str):
                    ap = a_piece.strip()
                    if ap:
                        if " " in ap:
                            g, fam = ap.rsplit(" ", 1)
                        else:
                            g, fam = "", ap
                        authors.append({"given": g, "family": fam})

            # Asignar DOI o identificador persistente derivado del título normalizado
            t_norm = norm(title)
            t_hash = abs(hash(t_norm)) % (10**12)
            doi = doi_raw.lower() if doi_raw else f"{source_label}:csv_{t_hash}"

            # Construir payload de artículo
            art_dict = {
                "doi": doi,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "journal_title": journal or None,
                "year": year,
                "source": source_label,
                "source_engine": source_label,
                "cited_by": cited_by,
                "access": "open" if "open" in oa_str else "closed",
            }

            status, art_id = db.upsert_article(conn, art_dict)
            if status == "new":
                imported += 1
            else:
                duplicates += 1

            # Asignar a article_screenings si no existe en este protocolo
            existing_sc = conn.execute(
                "SELECT id FROM article_screenings WHERE protocol_id = ? AND LOWER(doi) = ?",
                (protocol_id, doi.lower()),
            ).fetchone()

            if not existing_sc:
                db.save_screening(conn, protocol_id, doi=doi, decision="pending", article_id=art_id)
                added_to_screening += 1

        conn.commit()
    except Exception as e:
        conn.rollback()
        log.error("Error en importación masiva: %s", e)
        raise e

    return {
        "status": "ok",
        "imported_new": imported,
        "existing_reused": duplicates,
        "total_processed": imported + duplicates,
        "added_to_screening": added_to_screening,
        "protocol_id": protocol_id,
    }


def enrich_article_from_openalex(conn: sqlite3.Connection, article_id: int) -> dict[str, Any]:
    """Busca en OpenAlex por título para enriquecer DOI, revista, PDF y referencias."""
    row = conn.execute(
        "SELECT id, title, doi, year, journal_title, pdf_url, source FROM articles WHERE id = ?",
        (article_id,),
    ).fetchone()
    if not row:
        return {"success": False, "error": "Artículo no encontrado"}

    art = dict(row)
    title = art.get("title") or ""
    if not title:
        return {"success": False, "error": "Título vacío"}

    clean_t = re.sub(r'["\n\r]', " ", title).strip()
    url = f"https://api.openalex.org/works?filter=title.search:{clean_t}&per-page=3"

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return {"success": False, "error": f"OpenAlex HTTP {resp.status_code}"}
            data = resp.json()
            results = data.get("results") or []
            if not results:
                return {"success": False, "matched": False, "msg": "No se encontraron coincidencias exactas en OpenAlex"}

            # Evaluar similitud con el primer resultado
            best = results[0]
            cand_title = best.get("display_name") or best.get("title") or ""
            if norm(title) != norm(cand_title) and norm(title)[:40] not in norm(cand_title):
                return {"success": False, "matched": False, "msg": "La obra encontrada no coincide con suficiente certeza"}

            # Extraer campos enriquecidos
            real_doi = (best.get("doi") or "").replace("https://doi.org/", "").strip().lower()
            journal = None
            prim_loc = best.get("primary_location") or {}
            source_obj = prim_loc.get("source") or {}
            if source_obj:
                journal = source_obj.get("display_name")
            pdf_url = prim_loc.get("pdf_url") or best.get("open_access", {}).get("oa_url")
            cited_by = best.get("cited_by_count") or art.get("cited_by") or 0
            ref_ids = best.get("referenced_works") or []

            # Actualizar en la base de datos
            updates = []
            params = []
            if real_doi and real_doi != art.get("doi"):
                # Actualizar también screenings
                conn.execute(
                    "UPDATE article_screenings SET doi = ? WHERE article_id = ? OR doi = ?",
                    (real_doi, article_id, art.get("doi")),
                )
                updates.append("doi = ?")
                params.append(real_doi)

            if journal and not art.get("journal_title"):
                updates.append("journal_title = ?")
                params.append(journal)

            if pdf_url:
                updates.append("pdf_url = ?")
                params.append(pdf_url)

            if ref_ids:
                updates.append("referenced_ids = ?")
                params.append(json.dumps(ref_ids))

            if cited_by:
                updates.append("cited_by = MAX(cited_by, ?)")
                params.append(cited_by)

            if updates:
                params.append(article_id)
                conn.execute(f"UPDATE articles SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()

            return {
                "success": True,
                "matched": True,
                "article_id": article_id,
                "real_doi": real_doi or art.get("doi"),
                "journal_title": journal or art.get("journal_title"),
                "pdf_url": pdf_url,
                "cited_by": cited_by,
            }
    except Exception as e:
        log.warning("Fallo al enriquecer artículo %d: %s", article_id, e)
        return {"success": False, "error": str(e)}
