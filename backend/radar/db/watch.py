"""Anclas de palabras clave (watch) y bitácora de cosechas en SQLite."""
from __future__ import annotations

import sqlite3

from .articles import _row_to_article
from .connection import now_iso


def watch_list(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM watch_keywords ORDER BY created_at DESC, id DESC").fetchall()
    return [dict(r) for r in rows]


def watch_create(conn: sqlite3.Connection, keywords: str, label: str | None = None) -> dict:
    """Crea un ancla. last_seen_id = último artículo existente: solo contarán los NUEVOS."""
    from ..matching import parse_keywords

    kws = parse_keywords(keywords)
    if not kws:
        raise ValueError("keywords vacías tras parsear")
    canonical = ", ".join(kws)
    max_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM articles").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO watch_keywords (label, keywords, created_at, last_seen_id) VALUES (?, ?, ?, ?)",
        (label or canonical, canonical, now_iso(), max_id),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM watch_keywords WHERE id = ?", (cur.lastrowid,)).fetchone())


def watch_delete(conn: sqlite3.Connection, wid: int) -> bool:
    cur = conn.execute("DELETE FROM watch_keywords WHERE id = ?", (wid,))
    conn.commit()
    return cur.rowcount > 0


def _watch_candidates(conn: sqlite3.Connection, w: dict) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM articles WHERE id > ? ORDER BY id DESC LIMIT 800",
        (w["last_seen_id"],),
    ).fetchall()
    return [_row_to_article(r) for r in rows]


def watch_new_articles(conn: sqlite3.Connection, w: dict, limit: int = 20) -> list[dict]:
    """Artículos nuevos desde la última revisión que coinciden con las keywords del ancla."""
    from ..matching import parse_keywords, rank_articles

    kws = parse_keywords(w.get("keywords") or "")
    if not kws:
        return []
    ranked = rank_articles(_watch_candidates(conn, w), kws)
    return [a for a in ranked if a["match_score"] > 0][:limit]


def watch_new_count(conn: sqlite3.Connection, w: dict) -> int:
    """Conteo de artículos nuevos para el ancla. Early-exit si no hay candidatos (BUG-NEW-3)."""
    has_new = conn.execute(
        "SELECT 1 FROM articles WHERE id > ? LIMIT 1", (w["last_seen_id"],)
    ).fetchone()
    if not has_new:
        return 0
    return len(watch_new_articles(conn, w, limit=800))


def watch_mark_seen(conn: sqlite3.Connection, wid: int) -> None:
    max_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM articles").fetchone()[0]
    conn.execute("UPDATE watch_keywords SET last_seen_id = ? WHERE id = ?", (max_id, wid))
    conn.commit()


def watch_total(conn: sqlite3.Connection) -> dict:
    """Resumen para notificaciones: total de nuevas por ancla."""
    pins = []
    total = 0
    for w in watch_list(conn):
        n = watch_new_count(conn, w)
        total += n
        pins.append({"id": w["id"], "label": w["label"], "keywords": w["keywords"], "new": n})
    return {"total": total, "pins": pins}


def log_harvest(
    conn: sqlite3.Connection,
    source: str,
    status: str,
    found: int = 0,
    new: int = 0,
    notes: str = "",
) -> None:
    conn.execute(
        """INSERT INTO harvest_log (source, started_at, finished_at, status, articles_found, articles_new, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (source, now_iso(), now_iso(), status, found, new, notes),
    )
    conn.commit()


def last_harvest(conn: sqlite3.Connection, source: str) -> dict | None:
    r = conn.execute(
        "SELECT * FROM harvest_log WHERE source = ? ORDER BY id DESC LIMIT 1", (source,)
    ).fetchone()
    return dict(r) if r else None
