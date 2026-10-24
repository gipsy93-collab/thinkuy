"""Protocolos de revisión sistemática, cribado PRISMA y extracción JBI PCC."""
from __future__ import annotations

import json
import sqlite3

from .connection import now_iso

PROTOCOL_STATUSES = ("draft", "screening", "extracting", "completed")


def _protocol_json(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _protocol_parse(d: dict) -> dict:
    for col in ("inclusion_criteria", "exclusion_criteria", "target_disciplines", "seed_dois"):
        if d.get(col):
            try:
                d[col] = json.loads(d[col])
            except Exception:
                pass
    return d


def save_protocol(conn: sqlite3.Connection, protocol: dict, owner_id: str = "default") -> int:
    status = str(protocol.get("status") or "draft").strip().lower()
    if status not in PROTOCOL_STATUSES:
        raise ValueError(f"status inválido: {status!r} (válidos: {', '.join(PROTOCOL_STATUSES)})")
    ts = now_iso()
    user_owner = str(protocol.get("owner_id") or owner_id or "default").strip()
    cur = conn.execute(
        """INSERT INTO review_protocols
           (owner_id, title, research_question, framework, inclusion_criteria, exclusion_criteria, target_disciplines, date_from, date_to, seed_dois, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_owner,
            protocol["title"],
            protocol.get("research_question"),
            protocol.get("framework", "PICO"),
            _protocol_json(protocol.get("inclusion_criteria")),
            _protocol_json(protocol.get("exclusion_criteria")),
            _protocol_json(protocol.get("target_disciplines")),
            protocol.get("date_from"),
            protocol.get("date_to"),
            _protocol_json(protocol.get("seed_dois")),
            status,
            ts,
            ts,
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_protocol_status(conn: sqlite3.Connection, pid: int, status: str, owner_id: str | None = None) -> dict | None:
    """Avanza el estado PRISMA del protocolo (draft → screening → extracting → completed)."""
    clean = str(status or "").strip().lower()
    if clean not in PROTOCOL_STATUSES:
        raise ValueError(f"status inválido: {status!r} (válidos: {', '.join(PROTOCOL_STATUSES)})")
    if owner_id:
        cur = conn.execute(
            "UPDATE review_protocols SET status = ?, updated_at = ? WHERE id = ? AND (owner_id = ? OR owner_id = 'default')",
            (clean, now_iso(), pid, owner_id),
        )
    else:
        cur = conn.execute(
            "UPDATE review_protocols SET status = ?, updated_at = ? WHERE id = ?",
            (clean, now_iso(), pid),
        )
    conn.commit()
    if cur.rowcount == 0:
        return None
    return get_protocol(conn, pid, owner_id=owner_id)


def get_protocol(conn: sqlite3.Connection, pid: int, owner_id: str | None = None) -> dict | None:
    if owner_id:
        r = conn.execute(
            "SELECT * FROM review_protocols WHERE id = ? AND (owner_id = ? OR owner_id = 'default')",
            (pid, owner_id),
        ).fetchone()
    else:
        r = conn.execute("SELECT * FROM review_protocols WHERE id = ?", (pid,)).fetchone()
    if not r:
        return None
    return _protocol_parse(dict(r))


def list_protocols(conn: sqlite3.Connection, limit: int = 50, owner_id: str | None = None) -> list[dict]:
    if owner_id:
        rows = conn.execute(
            "SELECT * FROM review_protocols WHERE (owner_id = ? OR owner_id = 'default') ORDER BY id DESC LIMIT ?",
            (owner_id, limit),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM review_protocols ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_protocol_parse(dict(r)) for r in rows]


SCREENING_DECISIONS = ("pending", "included", "excluded", "maybe", "not_retrieved")
SCREENING_STAGES = ("title_abstract", "full_text")


def save_screening(
    conn: sqlite3.Connection,
    protocol_id: int,
    doi: str,
    decision: str,
    reason: str | None = None,
    article_id: int | None = None,
    screened_by: str = "researcher",
    owner_id: str = "default",
    stage: str = "title_abstract",
) -> dict:
    """Registra o actualiza la decisión de screening de un artículo en un protocolo.

    `stage` distingue la etapa PRISMA 2020: `title_abstract` (por defecto) o `full_text`.
    """
    clean = decision.strip().lower()
    if clean not in SCREENING_DECISIONS:
        raise ValueError(f"decision inválida: {decision!r} (válidas: {', '.join(SCREENING_DECISIONS)})")
    clean_stage = str(stage or "title_abstract").strip().lower()
    if clean_stage not in SCREENING_STAGES:
        raise ValueError(f"stage inválido: {stage!r} (válidos: {', '.join(SCREENING_STAGES)})")
    ts = now_iso()
    norm_doi = doi.strip().lower()
    if article_id is None:
        if norm_doi.startswith("article:"):
            s_id = norm_doi[8:].strip()
            if s_id.isdigit():
                article_id = int(s_id)
        if not article_id:
            art_row = conn.execute("SELECT id FROM articles WHERE doi = ?", (norm_doi,)).fetchone()
            if art_row:
                article_id = art_row["id"]
    conn.execute(
        """INSERT INTO article_screenings (owner_id, protocol_id, article_id, doi, decision, reason, screened_by, stage, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(protocol_id, doi, stage) DO UPDATE SET
             owner_id    = COALESCE(excluded.owner_id, article_screenings.owner_id),
             article_id  = COALESCE(excluded.article_id, article_screenings.article_id),
             decision    = excluded.decision,
             reason      = excluded.reason,
             screened_by = excluded.screened_by,
             created_at  = excluded.created_at""",
        (owner_id, protocol_id, article_id, norm_doi, clean, reason, screened_by, clean_stage, ts),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM article_screenings WHERE protocol_id = ? AND doi = ? AND stage = ?",
        (protocol_id, norm_doi, clean_stage),
    ).fetchone()
    return dict(row) if row else {}


def list_screenings(
    conn: sqlite3.Connection,
    protocol_id: int,
    decision: str | None = None,
    limit: int = 200,
    owner_id: str | None = None,
    stage: str | None = None,
) -> list[dict]:
    """Lista las decisiones de screening de un protocolo unidas con los metadatos del artículo."""
    base_sql = """
        SELECT 
            s.id,
            s.owner_id,
            s.protocol_id,
            s.article_id,
            s.doi,
            s.decision,
            s.reason,
            s.screened_by,
            s.stage,
            s.created_at,
            COALESCE(a.title, s.doi) AS title,
            a.abstract,
            a.authors,
            a.year,
            a.journal_title,
            a.source,
            a.cited_by,
            a.url,
            a.pdf_url
        FROM article_screenings s
        LEFT JOIN articles a ON a.id = s.article_id
        WHERE s.protocol_id = ?
    """
    params: list = [protocol_id]
    if owner_id:
        base_sql += " AND (s.owner_id = ? OR s.owner_id = 'default')"
        params.append(owner_id)
    if decision:
        base_sql += " AND s.decision = ?"
        params.append(decision.strip().lower())
    if stage:
        base_sql += " AND s.stage = ?"
        params.append(stage.strip().lower())
    base_sql += " ORDER BY s.id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(base_sql, params).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        if d.get("authors") and isinstance(d["authors"], str):
            try:
                d["authors"] = json.loads(d["authors"])
            except Exception:
                pass
        results.append(d)
    return results


def link_screening_article(
    conn: sqlite3.Connection,
    protocol_id: int,
    doi: str,
    article_id: int,
) -> int:
    """Enlaza un cribado con el artículo recién indexado, sin tocar la decisión."""
    if not doi or not article_id:
        return 0
    cur = conn.execute(
        """UPDATE article_screenings SET article_id = ?
            WHERE protocol_id = ? AND doi = ? AND (article_id IS NULL OR article_id <= 0)""",
        (article_id, protocol_id, doi.strip().lower()),
    )
    conn.commit()
    return cur.rowcount


def log_protocol_search(
    conn: sqlite3.Connection,
    protocol_id: int,
    source: str,
    records_identified: int = 0,
    query: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    owner_id: str = "default",
) -> int:
    """Registra una búsqueda ejecutada sobre una fuente (identificación PRISMA 2020, ítem 6).

    Una fila por fuente y por búsqueda: cuántos registros devolvió la fuente, con qué consulta,
    qué límite temporal y en qué fecha. Es la base para reconstruir la identificación y los
    duplicados removidos del diagrama de flujo **sin inventar cifras**.
    """
    cur = conn.execute(
        """INSERT INTO protocol_searches
           (owner_id, protocol_id, source, query, year_from, year_to, records_identified, searched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (owner_id, protocol_id, str(source), query, year_from, year_to,
         int(records_identified or 0), now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def list_protocol_searches(conn: sqlite3.Connection, protocol_id: int,
                           owner_id: str | None = None) -> list[dict]:
    """Historial de búsquedas de un protocolo (trazabilidad de la estrategia)."""
    sql = "SELECT * FROM protocol_searches WHERE protocol_id = ?"
    params: list = [protocol_id]
    if owner_id:
        sql += " AND (owner_id = ? OR owner_id = 'default')"
        params.append(owner_id)
    sql += " ORDER BY id DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def screening_flow_counts(conn: sqlite3.Connection, protocol_id: int, owner_id: str | None = None) -> dict:
    """Conteos del diagrama de flujo PRISMA 2020 (identificación → cribado → incluidos).

    Tres garantías:

    - La **identificación** sale del registro de búsquedas del protocolo (`protocol_searches`),
      no de la tabla global de artículos. Cada fuente (OpenAlex, OpenAIRE, Dialnet, importación)
      aporta su cifra y su fecha.
    - Los **duplicados removidos** se calculan como `identificados − registros únicos`, que es la
      definición de PRISMA. Antes se contaba un grupo de DOI duplicados de **toda** la base y
      siempre daba 0 (porque `articles.doi` es UNIQUE).
    - La **segunda etapa** (texto completo) es no destructiva: si el protocolo no tiene registros
      de texto completo, los informes buscados/evaluados/excluidos se declaran `None` y el
      incluido de título/resumen sigue siendo el final. Si los tiene, el incluido final pasa a ser
      el de texto completo y los recuadros de la segunda etapa se calculan de verdad.
    """
    where_owner = " AND (owner_id = ? OR owner_id = 'default')" if owner_id else ""
    where_owner_s = " AND (s.owner_id = ? OR s.owner_id = 'default')" if owner_id else ""
    owner_param = [owner_id] if owner_id else []

    # Identificación: registros por fuente (suma de todas las búsquedas del protocolo)
    ident_rows = conn.execute(
        f"SELECT source, SUM(records_identified) AS n FROM protocol_searches "
        f"WHERE protocol_id = ?{where_owner} GROUP BY source",
        [protocol_id] + owner_param,
    ).fetchall()
    identificados_por_fuente = {r["source"]: int(r["n"] or 0) for r in ident_rows}
    total_identificados = sum(identificados_por_fuente.values())

    # Registros únicos que entraron al cribado (independiente de la etapa)
    total_unicos = conn.execute(
        f"SELECT COUNT(DISTINCT doi) AS n FROM article_screenings WHERE protocol_id = ?{where_owner}",
        [protocol_id] + owner_param,
    ).fetchone()["n"]

    # Decisiones por etapa
    def _cuenta(etapa: str | None) -> dict:
        extra = " AND stage = ?" if etapa else ""
        salida = {}
        for dec in SCREENING_DECISIONS:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM article_screenings WHERE protocol_id = ? AND decision = ?{extra}{where_owner}",
                [protocol_id, dec] + ([etapa] if etapa else []) + owner_param,
            ).fetchone()
            salida[dec] = row["n"]
        return salida

    ta = _cuenta("title_abstract")
    ft = _cuenta("full_text")

    tiene_full_text = conn.execute(
        "SELECT 1 FROM article_screenings WHERE protocol_id = ? AND stage = 'full_text' LIMIT 1",
        [protocol_id],
    ).fetchone() is not None

    # Exclusion reasons breakdown (título/resumen si hay dos etapas; si no, las que haya)
    razones_etapa = " AND stage = 'title_abstract'" if tiene_full_text else ""
    reason_rows = conn.execute(
        f"SELECT reason, COUNT(*) AS n FROM article_screenings WHERE protocol_id = ? AND decision = 'excluded' AND reason IS NOT NULL{razones_etapa}{where_owner} GROUP BY reason ORDER BY n DESC",
        [protocol_id] + owner_param,
    ).fetchall()
    exclusion_reasons = {r["reason"]: r["n"] for r in reason_rows}

    # Atribución por fuente de los registros cribados (por clave primaria)
    source_rows = conn.execute(f"""
        SELECT COALESCE(a.source, 'sin_articulo') AS source, COUNT(DISTINCT s.doi) AS cnt
        FROM article_screenings s
        LEFT JOIN articles a ON a.id = s.article_id
        WHERE s.protocol_id = ?{where_owner_s}
        GROUP BY COALESCE(a.source, 'sin_articulo')
    """, [protocol_id] + owner_param).fetchall()
    sources = {r["source"]: r["cnt"] for r in source_rows}

    duplicados_removidos = max(total_identificados - total_unicos, 0)

    if tiene_full_text:
        # Dos etapas: el incluido de título/resumen avanza a texto completo; el final es el de texto completo.
        registros_cribados = ta["included"] + ta["excluded"] + ta["maybe"]
        registros_excluidos = ta["excluded"]
        informes_buscados = ta["included"] + ta["maybe"]
        informes_no_recuperados = ft["not_retrieved"]
        informes_evaluados = ft["included"] + ft["excluded"]
        informes_excluidos = ft["excluded"]
        incluidos_finales = ft["included"]
        en_cola = ta["pending"]
        dudosos = ta["maybe"]
    else:
        # Una etapa (comportamiento previo, intacto): el incluido de título/resumen es el final.
        registros_cribados = ta["included"] + ta["excluded"] + ta["maybe"]
        registros_excluidos = ta["excluded"]
        informes_buscados = None
        informes_no_recuperados = None
        informes_evaluados = None
        informes_excluidos = None
        incluidos_finales = ta["included"]
        en_cola = ta["pending"]
        dudosos = ta["maybe"]

    prisma_2020 = {
        "identificacion": {
            "bases_de_datos": identificados_por_fuente,
            "registros": {},
            "otras_fuentes": {},
            "total": total_identificados,
        },
        "removidos_antes_del_cribado": {
            "duplicados": duplicados_removidos,
            "no_elegibles_por_automatizacion": 0,
            "otras_razones": 0,
            "total": duplicados_removidos,
        },
        "cribado": {
            "registros_unicos": total_unicos,
            "registros_cribados": registros_cribados,
            "registros_excluidos": registros_excluidos,
            "en_cola": en_cola,
            "dudosos": dudosos,
            "motivos_exclusion": exclusion_reasons,
            "informes_buscados": informes_buscados,
            "informes_no_recuperados": informes_no_recuperados,
            "informes_evaluados": informes_evaluados,
            "informes_excluidos": informes_excluidos,
        },
        "incluidos": {
            "estudios": incluidos_finales,
            "informes": incluidos_finales,
        },
        "segunda_etapa_implementada": tiene_full_text,
    }

    return {
        "protocol_id": protocol_id,
        # Claves retrocompatibles (la interfaz actual las consume)
        "total_identified": total_identificados,
        "duplicates_detected": duplicados_removidos,
        "pending": en_cola,
        "included": incluidos_finales,
        "excluded": registros_excluidos,
        "maybe": dudosos,
        "exclusion_reasons": exclusion_reasons,
        "sources": sources,
        # Estructura PRISMA 2020
        "prisma_2020": prisma_2020,
    }


def save_charting(
    conn: sqlite3.Connection,
    protocol_id: int,
    doi: str,
    data: dict,
    article_id: int | None = None,
    owner_id: str = "default",
) -> dict:
    """Guarda o actualiza los datos de charteo (extracción estructurada) de un artículo."""
    ts = now_iso()
    norm_doi = doi.strip().lower()
    conn.execute(
        """INSERT INTO charting_data
           (owner_id, protocol_id, article_id, doi, population, concept, context, methodology, key_findings, limitations, quality_score, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(protocol_id, doi) DO UPDATE SET
             owner_id      = COALESCE(excluded.owner_id, charting_data.owner_id),
             population    = excluded.population,
             concept       = excluded.concept,
             context       = excluded.context,
             methodology   = excluded.methodology,
             key_findings  = excluded.key_findings,
             limitations   = excluded.limitations,
             quality_score = excluded.quality_score,
             notes         = excluded.notes,
             updated_at    = excluded.updated_at""",
        (
            owner_id, protocol_id, article_id, norm_doi,
            data.get("population"), data.get("concept"), data.get("context"),
            data.get("methodology"), data.get("key_findings"), data.get("limitations"),
            data.get("quality_score"), data.get("notes"),
            ts, ts,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM charting_data WHERE protocol_id = ? AND doi = ?",
        (protocol_id, norm_doi),
    ).fetchone()
    return dict(row) if row else {}


def list_charting(
    conn: sqlite3.Connection,
    protocol_id: int,
    limit: int = 200,
    owner_id: str | None = None,
) -> list[dict]:
    if owner_id:
        rows = conn.execute(
            "SELECT * FROM charting_data WHERE protocol_id = ? AND (owner_id = ? OR owner_id = 'default') ORDER BY id DESC LIMIT ?",
            (protocol_id, owner_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM charting_data WHERE protocol_id = ? ORDER BY id DESC LIMIT ?",
            (protocol_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_charting_entry(
    conn: sqlite3.Connection,
    protocol_id: int,
    doi: str,
    owner_id: str | None = None,
) -> dict | None:
    if owner_id:
        row = conn.execute(
            "SELECT * FROM charting_data WHERE protocol_id = ? AND doi = ? AND (owner_id = ? OR owner_id = 'default')",
            (protocol_id, doi.strip().lower(), owner_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM charting_data WHERE protocol_id = ? AND doi = ?",
            (protocol_id, doi.strip().lower()),
        ).fetchone()
    return dict(row) if row else None


def export_protocol_articles(
    conn: sqlite3.Connection,
    protocol_id: int,
    decision_filter: str | None = "included",
    owner_id: str | None = None,
) -> list[dict]:
    """Recupera artículos incluidos en un protocolo con metadatos completos para exportación."""
    cond = "s.protocol_id = ?"
    params: list = [protocol_id]
    if owner_id:
        cond += " AND (s.owner_id = ? OR s.owner_id = 'default')"
        params.append(owner_id)
    if decision_filter:
        cond += " AND s.decision = ?"
        params.append(decision_filter)
        if decision_filter == "included":
            # Con dos etapas, el incluido FINAL es el de texto completo; sin ellas, el de
            # título/resumen. Evita exportar lo que avanzó y luego se excluyó a texto completo.
            tiene_ft = conn.execute(
                "SELECT 1 FROM article_screenings WHERE protocol_id = ? AND stage = 'full_text' LIMIT 1",
                (protocol_id,),
            ).fetchone()
            cond += " AND s.stage = ?"
            params.append("full_text" if tiene_ft else "title_abstract")

    articles = conn.execute(
        f"""SELECT a.* FROM article_screenings s
              JOIN articles a ON a.id = s.article_id
             WHERE {cond}""",
        params,
    ).fetchall()

    sin_articulo = conn.execute(
        f"""SELECT s.doi FROM article_screenings s
              LEFT JOIN articles a ON a.id = s.article_id
             WHERE a.id IS NULL AND {cond}""",
        params,
    ).fetchall()

    results = []
    for a in articles:
        art = dict(a)
        chart = get_charting_entry(conn, protocol_id, art.get("doi") or "", owner_id=owner_id)
        if chart:
            art["charting"] = chart
        results.append(art)
    for fila in sin_articulo:
        d = str(fila["doi"] or "")
        chart = get_charting_entry(conn, protocol_id, d, owner_id=owner_id)
        results.append({
            "doi": d,
            "title": (chart.get("title") if chart else "") or d,
            "year": (chart.get("year") if chart else None),
            "journal_title": "",
            "abstract": "",
            "authors": "[]",
            "charting": chart or {},
        })
    return results
