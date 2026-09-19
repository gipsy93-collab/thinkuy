"""Gestión de revistas científicas y anclas editoriales en SQLite."""
from __future__ import annotations

import json
import re
import sqlite3

from .connection import now_iso

_ISSN_RE = re.compile(r"^\d{4}-\d{3}[\dX]$")


def _journal_issn(value: str | None) -> str | None:
    """Normaliza y valida un ISSN antes de usarlo como identidad de revista."""
    text = (value or "").strip().upper()
    if _ISSN_RE.match(text):
        return text
    return None


def _journal_title(value: str | None) -> str | None:
    """Limpia un título de revista preservando su forma de presentación."""
    text = " ".join(str(value or "").split())
    return text[:300] if len(text) >= 4 else None


def upsert_journal(conn: sqlite3.Connection, j: dict) -> int:
    cur = conn.execute(
        """INSERT INTO journals (title, issn_print, issn_online, country, source, collection, subject_areas, auto_discovered, last_harvest)
           VALUES (:title, :issn_print, :issn_online, :country, :source, :collection, :subject_areas, :auto_discovered, :last_harvest)
           ON CONFLICT(title) DO UPDATE SET
             issn_print    = COALESCE(excluded.issn_print, journals.issn_print),
             issn_online   = COALESCE(excluded.issn_online, journals.issn_online),
             country       = COALESCE(excluded.country, journals.country),
             collection    = COALESCE(excluded.collection, journals.collection),
             subject_areas = COALESCE(excluded.subject_areas, journals.subject_areas),
             source        = journals.source
           RETURNING id""",
        {
            "title": j["title"],
            "issn_print": j.get("issn_print"),
            "issn_online": j.get("issn_online"),
            "country": j.get("country"),
            "source": j.get("source", "seed"),
            "collection": j.get("collection"),
            "subject_areas": json.dumps(j.get("subject_areas") or [], ensure_ascii=False),
            "auto_discovered": 1 if j.get("auto_discovered") else 0,
            "last_harvest": j.get("last_harvest"),
        },
    )
    row = cur.fetchone()
    # Si la revista descubierta tiene colección, vincularla también a revistas existentes por ISSN
    coll = j.get("collection")
    if coll:
        for issn in (j.get("issn_print"), j.get("issn_online")):
            if issn:
                conn.execute(
                    """UPDATE journals SET collection = ?
                       WHERE (issn_print = ? OR issn_online = ?) AND collection IS NULL""",
                    (coll, issn, issn),
                )
    conn.commit()
    return row["id"] if row else None


def ensure_journal_from_article(
    conn: sqlite3.Connection,
    *,
    source: str,
    title: str | None,
    issn: str | None,
    collection: str | None = None,
) -> tuple[bool, int | None]:
    """Registra la revista de un artículo descubierto sin duplicar ISSN ni título.

    Devuelve (es_nueva, journal_id). Solo completa los campos que falten en una
    revista ya existente; nunca sobrescribe su fuente original.
    """
    clean_title = _journal_title(title)
    clean_issn = _journal_issn(issn)
    if not clean_title and not clean_issn:
        return False, None

    candidates = []
    if clean_issn:
        candidates = conn.execute(
            """SELECT * FROM journals
               WHERE issn_print = ? OR issn_online = ?""",
            (clean_issn, clean_issn),
        ).fetchall()
    if not candidates and clean_title:
        candidates = conn.execute(
            """SELECT * FROM journals WHERE title = ? COLLATE NOCASE""",
            (clean_title,),
        ).fetchall()

    if candidates:
        journal = dict(candidates[0])
        updates = {}
        if not journal.get("title") and clean_title:
            updates["title"] = clean_title
        if clean_issn and not journal.get("issn_print") and not journal.get("issn_online"):
            updates["issn_print"] = clean_issn
        if not journal.get("collection") and collection:
            updates["collection"] = collection
        if updates:
            assignments = ", ".join(f"{column} = ?" for column in updates)
            conn.execute(
                f"UPDATE journals SET {assignments} WHERE id = ?",
                (*updates.values(), journal["id"]),
            )
            conn.commit()
        return False, journal["id"]

    if not clean_title:
        return False, None
    journal_id = upsert_journal(
        conn,
        {
            "title": clean_title,
            "issn_print": clean_issn,
            "issn_online": None,
            "country": None,
            "source": source or "live",
            "collection": collection,
            "subject_areas": [],
            "auto_discovered": True,
            "last_harvest": now_iso(),
        },
    )
    return True, journal_id


def all_journals(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM journals ORDER BY title").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["subject_areas"] = json.loads(d.get("subject_areas") or "[]")
        except json.JSONDecodeError:
            d["subject_areas"] = []
        out.append(d)
    return out


def journals_with_issn(conn: sqlite3.Connection) -> list[dict]:
    return [
        j
        for j in all_journals(conn)
        if j.get("issn_print") or j.get("issn_online")
    ]


def count_journals(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM journals").fetchone()["n"]
