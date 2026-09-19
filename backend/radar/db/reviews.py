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


SCREENING_DECISIONS = ("pending", "included", "excluded", "maybe")


def save_screening(
    conn: sqlite3.Connection,
    protocol_id: int,
    doi: str,
    decision: str,
    reason: str | None = None,
    article_id: int | None = None,
    screened_by: str = "researcher",
    owner_id: str = "default",
) -> dict:
    """Registra o actualiza la decisión de screening de un artículo en un protocolo."""
    clean = decision.strip().lower()
    if clean not in SCREENING_DECISIONS:
        raise ValueError(f"decision inválida: {decision!r} (válidas: {', '.join(SCREENING_DECISIONS)})")
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
        """INSERT INTO article_screenings (owner_id, protocol_id, article_id, doi, decision, reason, screened_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(protocol_id, doi) DO UPDATE SET
             owner_id    = COALESCE(excluded.owner_id, article_screenings.owner_id),
             article_id  = COALESCE(excluded.article_id, article_screenings.article_id),
             decision    = excluded.decision,
             reason      = excluded.reason,
             screened_by = excluded.screened_by,
             created_at  = excluded.created_at""",
        (owner_id, protocol_id, article_id, norm_doi, clean, reason, screened_by, ts),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM article_screenings WHERE protocol_id = ? AND doi = ?",
        (protocol_id, norm_doi),
    ).fetchone()
    return dict(row) if row else {}


def list_screenings(
    conn: sqlite3.Connection,
    protocol_id: int,
    decision: str | None = None,
    limit: int = 200,
    owner_id: str | None = None,
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


def screening_flow_counts(conn: sqlite3.Connection, protocol_id: int, owner_id: str | None = None) -> dict:
    """Genera los conteos para el diagrama de flujo PRISMA-ScR."""
    where_owner = " AND (owner_id = ? OR owner_id = 'default')" if owner_id else ""
    where_owner_s = " AND (s.owner_id = ? OR s.owner_id = 'default')" if owner_id else ""
    owner_param = [owner_id] if owner_id else []

    total_identified = conn.execute(
        f"SELECT COUNT(*) as n FROM article_screenings WHERE protocol_id = ?{where_owner}",
        [protocol_id] + owner_param,
    ).fetchone()["n"]
    counts = {}
    for dec in SCREENING_DECISIONS:
        row = conn.execute(
            f"SELECT COUNT(*) as n FROM article_screenings WHERE protocol_id = ? AND decision = ?{where_owner}",
            [protocol_id, dec] + owner_param,
        ).fetchone()
        counts[dec] = row["n"]
    # Exclusion reasons breakdown
    reason_rows = conn.execute(
        f"SELECT reason, COUNT(*) as n FROM article_screenings WHERE protocol_id = ? AND decision = 'excluded' AND reason IS NOT NULL{where_owner} GROUP BY reason ORDER BY n DESC",
        [protocol_id] + owner_param,
    ).fetchall()
    exclusion_reasons = {r["reason"]: r["n"] for r in reason_rows}
    # Duplicate count
    dup_count = 0
    try:
        dup_count = conn.execute(
            "SELECT COUNT(*) as n FROM (SELECT doi, COUNT(*) as cnt FROM articles WHERE doi IS NOT NULL AND doi != '' GROUP BY LOWER(doi) HAVING cnt > 1)"
        ).fetchone()["n"]
    except Exception:
        pass
    # Source breakdown — por clave primaria
    source_rows = conn.execute(f"""
        SELECT COALESCE(a.source, 'sin_articulo') AS source, COUNT(*) as cnt
        FROM article_screenings s
        LEFT JOIN articles a ON a.id = s.article_id
        WHERE s.protocol_id = ?{where_owner_s}
        GROUP BY COALESCE(a.source, 'sin_articulo')
    """, [protocol_id] + owner_param).fetchall()
    sources = {r["source"]: r["cnt"] for r in source_rows}

    return {
        "protocol_id": protocol_id,
        "total_identified": total_identified,
        "duplicates_detected": dup_count,
        "pending": counts.get("pending", 0),
        "included": counts.get("included", 0),
        "excluded": counts.get("excluded", 0),
        "maybe": counts.get("maybe", 0),
        "exclusion_reasons": exclusion_reasons,
        "sources": sources,
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
