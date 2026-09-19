"""Subrouter de la API de Thinkuy."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query

from ... import db, network
from ...matching import parse_keywords
from ..common import (
    _with_display_keywords,
)

router = APIRouter(tags=['harvest'])
log = logging.getLogger('radar.api.harvest')

_harvest_lock = False

def _execute_harvest_task(sources_list: list[str], days: int):
    """Tarea ejecutada en segundo plano para no congelar el servidor FastAPI."""
    global _harvest_lock
    try:
        from ...harvester.pipeline import run_pipeline
        log.info("Iniciando cosecha en segundo plano (días=%d, fuentes=%s)", days, sources_list)
        run_pipeline(sources=sources_list, days=days)
        # Invalidar caché de red social tras nuevos artículos
        network.invalidate_network_cache()
        log.info("Cosecha en segundo plano finalizada con éxito")
    except Exception as e:
        log.error("Error durante la cosecha en segundo plano: %s", e)
    finally:
        _harvest_lock = False


@router.get("/api/watch")
def watch_list_endpoint():
    """Lista ligera de anclas guardadas sin cómputo de novedades (O(1)). Úsa esta ruta
    para renderizar la lista de anclas; usa /api/watch/total para los conteos."""
    conn = db.connect()
    try:
        return {"pins": db.watch_list(conn)}
    finally:
        conn.close()


@router.get("/api/watch/total")
def watch_total():
    """Anclas con conteo de publicaciones nuevas desde la última revisión.
    Más costoso que /api/watch; optimizado con early-exit por ancla."""
    conn = db.connect()
    try:
        return db.watch_total(conn)
    finally:
        conn.close()


@router.post("/api/watch")
def watch_create(payload: dict = Body(...)):
    keywords = str(payload.get("keywords") or "").strip()
    if not keywords:
        raise HTTPException(422, "keywords es obligatorio")
    label = str(payload.get("label") or "").strip() or keywords
    conn = db.connect()
    try:
        w = db.watch_create(conn, keywords, label)
        return w
    finally:
        conn.close()


@router.delete("/api/watch/{wid}")
def watch_delete(wid: int):
    conn = db.connect()
    try:
        if not db.watch_delete(conn, wid):
            raise HTTPException(404, "Ancla no encontrada")
        return {"ok": True}
    finally:
        conn.close()


@router.get("/api/watch/{wid}/new")
def watch_new(wid: int, mark: int = Query(0, ge=0, le=1),
              limit: int = Query(20, ge=1, le=50)):
    """Artículos nuevos para el ancla desde la última revisión (mark=1 la marca como vista)."""
    conn = db.connect()
    try:
        w = next((x for x in db.watch_list(conn) if x["id"] == wid), None)
        if not w:
            raise HTTPException(404, "Ancla no encontrada")
        articles = db.watch_new_articles(conn, w, limit=limit)
        _with_display_keywords(articles, candidate_terms=parse_keywords(w.get("keywords") or ""))
        if mark:
            db.watch_mark_seen(conn, wid)
        return {"id": wid, "label": w["label"], "keywords": w["keywords"],
                "count": len(articles), "articles": articles}
    finally:
        conn.close()


@router.post("/api/harvest/run")
def run_harvest(background_tasks: BackgroundTasks, days: int = Query(90, ge=1), sources: str = "scielo,crossref"):
    global _harvest_lock
    if _harvest_lock:
        raise HTTPException(409, "Ya hay una cosecha en curso en segundo plano")
    _harvest_lock = True
    sources_list = [s.strip() for s in sources.split(",") if s.strip()]
    background_tasks.add_task(_execute_harvest_task, sources_list, days)
    return {
        "status": "started",
        "message": "Cosecha iniciada en segundo plano. El servidor continuará respondiendo con normalidad.",
        "days": days,
        "sources": sources_list,
    }


@router.get("/api/harvest/status")
def harvest_status():
    """Estado de la cosecha actual y registro de la última ejecución."""
    conn = db.connect()
    try:
        last = conn.execute("SELECT * FROM harvest_log ORDER BY id DESC LIMIT 5").fetchall()
        return {
            "running": bool(_harvest_lock),
            "recent_logs": [dict(r) for r in last],
        }
    finally:
        conn.close()

