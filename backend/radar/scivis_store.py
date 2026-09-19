# -*- coding: utf-8 -*-
"""
radar/scivis_store.py — Persistencia de auditorías SCIVIS.

Dos funciones en una base SQLite ligera (data/scivis_store.db):
  1. Caché TTL de auditorías completas (evita re-consultar CDX/OpenAlex/Wikipedia a cada request).
  2. Serie longitudinal REAL de nuestras propias auditorías: cada medición queda registrada con
     fecha, release y valores, de modo que con el tiempo se acumula una trayectoria verificable
     de la propia herramienta (sin ningún dato interpolado).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time

from . import config

log = logging.getLogger("radar.scivis_store")

STORE_DB = str(config.DATA_DIR / "scivis_store.db")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(STORE_DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT,
            domain TEXT,
            journal_title TEXT,
            harmonic_rank INTEGER,
            harmonic_val REAL,
            pagerank_rank INTEGER,
            pagerank_val REAL,
            release TEXT,
            total_domains INTEGER,
            payload TEXT,
            created_at REAL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audits_domain ON audits(domain)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audits_created ON audits(created_at)")
    conn.commit()
    return conn


def cache_get(query: str, ttl_hours: int = 24) -> dict | None:
    """Devuelve la auditoría cacheada si no ha expirado, o None."""
    try:
        conn = _conn()
        row = conn.execute(
            "SELECT payload, created_at FROM audits WHERE query = ? ORDER BY created_at DESC LIMIT 1",
            (query,),
        ).fetchone()
        conn.close()
        if row and (time.time() - row["created_at"]) < ttl_hours * 3600:
            return json.loads(row["payload"])
    except Exception as e:
        log.debug("Caché SCIVIS no disponible: %s", e)
    return None


def cache_put(payload: dict) -> None:
    """Registra la auditoría en la serie longitudinal (y alimenta la caché TTL)."""
    try:
        harm = payload.get("harmonic_centrality") or {}
        conn = _conn()
        conn.execute(
            """INSERT INTO audits (query, domain, journal_title, harmonic_rank, harmonic_val,
               pagerank_rank, pagerank_val, release, total_domains, payload, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                payload.get("query", ""),
                (payload.get("domain") or ""),
                (payload.get("journal_title") or ""),
                harm.get("harmonic_rank"),
                harm.get("harmonic_val"),
                harm.get("pagerank_rank"),
                harm.get("pagerank_val"),
                harm.get("release"),
                harm.get("total_domains"),
                json.dumps(payload, ensure_ascii=False),
                time.time(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("No se pudo persistir auditoría SCIVIS: %s", e)


def audit_history(domain: str, limit: int = 20) -> list[dict]:
    """Serie real de nuestras propias auditorías para un dominio (verificable en el tiempo)."""
    try:
        conn = _conn()
        rows = conn.execute(
            """SELECT query, domain, journal_title, harmonic_rank, harmonic_val,
                      pagerank_rank, pagerank_val, release, created_at
               FROM audits
               WHERE domain = ? OR query = ?
               ORDER BY created_at DESC LIMIT ?""",
            (domain, domain, limit),
        ).fetchall()
        conn.close()
        return [
            {
                "query": r["query"],
                "journal_title": r["journal_title"],
                "harmonic_rank": r["harmonic_rank"],
                "harmonic_val": r["harmonic_val"],
                "pagerank_rank": r["pagerank_rank"],
                "pagerank_val": r["pagerank_val"],
                "release": r["release"],
                "audited_at": r["created_at"],
            }
            for r in rows
        ]
    except Exception as e:
        log.debug("Sin historial SCIVIS: %s", e)
        return []