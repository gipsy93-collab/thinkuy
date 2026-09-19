"""Subrouter de la API de Thinkuy."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query, Request

from ... import config, db, network, profile, tracker

router = APIRouter(tags=['admin'])
log = logging.getLogger('radar.api.admin')


def _collect_route_paths(obj) -> set[str]:
    rutas = set()
    if not obj:
        return rutas
    for r in getattr(obj, "routes", []):
        p = getattr(r, "path", None)
        if p:
            rutas.add(p)
        orig = getattr(r, "original_router", None)
        if orig:
            rutas.update(_collect_route_paths(orig))
    return rutas


def build_fingerprint(app=None) -> dict:
    """Huella del código cargado en memoria: ruta, fecha del archivo y endpoints clave."""
    ruta = Path(__file__).resolve().parent.parent / "main.py"
    try:
        modificado = datetime.fromtimestamp(ruta.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        modificado = None
    rutas = _collect_route_paths(app)
    return {
        "codigo": str(ruta),
        "main_py_modificado": modificado,
        "rutas_totales": len(rutas),
        "endpoints_nuevos": {
            "/api/metadata/abstract": "/api/metadata/abstract" in rutas,
            "/api/editorial/journal/profile": "/api/editorial/journal/profile" in rutas,
            "/api/fulltext/backfill": "/api/fulltext/backfill" in rutas,
        },
    }

@router.get("/api/health")
def health(request: Request = None):
    """Estado del servicio **con huella de compilación**.

    `build` existe para detectar en una sola petición una instancia obsoleta: si el proceso
    lleva cargado un `main.py` viejo mientras el disco ya tiene otro, los endpoints nuevos
    responden 404 y la interfaz falla sin decir por qué. Con la huella se ve al instante.
    """
    conn = db.connect()
    try:
        st = db.stats(conn)
        return {
            "status": "ok",
            "version": config.VERSION,
            "filosofia": "No busques el paper. Deja que el paper te encuentre.",
            "field": profile.field_profile.field_label,
            "profile": profile.field_profile.id,
            "build": build_fingerprint(request.app if request else None),
            "stats": st,
        }
    finally:
        conn.close()


@router.get("/api/field")
def field_info():
    active_db = db.db_path_for_field(profile.field_profile.id)
    return {
        "field": profile.field_profile.id,
        "name": profile.field_profile.field_label,
        "available": profile.available_fields(),
        "db": str(active_db),
    }


@router.post("/api/field/set")
def field_set(payload: dict = Body(...)):
    """Cambia el campo activo en runtime (recarga perfil).

    El perfil activo vive SOLO en `profile.field_profile`; ningún módulo guarda
    su propia copia, para que el cambio se propague a lectura y escritura.
    """
    field_id = str(payload.get("field") or "").strip()
    if field_id not in profile.available_fields():
        raise HTTPException(404, f"Perfil «{field_id}» no encontrado")
    profile.reload(field_id)
    active_db = db.db_path_for_field(field_id)
    network.invalidate_network_cache()
    conn = db.connect_for_field(field_id)
    db.init_db(conn)
    db.rebuild_anchor_signals(conn)
    conn.close()
    return {"ok": True, "field": profile.field_profile.id,
            "name": profile.field_profile.field_label, "db": str(active_db)}


@router.get("/api/doi/track")
def track_doi_endpoint(
    doi: str = Query(..., description="DOI del artículo científico"),
    refresh: bool = Query(False, description="Forzar actualización en vivo ignorando caché"),
):
    """Rastrea el impacto y difusión de un DOI en la web abierta con granularidad."""
    cleaned = tracker.clean_doi(doi)
    if not cleaned:
        raise HTTPException(400, "DOI inválido o vacío")
    data = tracker.track_doi(cleaned, force_refresh=refresh)
    return data


@router.get("/api/doi/history")
def track_doi_history_endpoint(
    doi: str = Query(..., description="DOI del artículo científico"),
):
    """Devuelve la serie temporal de difusión registrada para un DOI."""
    cleaned = tracker.clean_doi(doi)
    if not cleaned:
        raise HTTPException(400, "DOI inválido o vacío")
    return {"doi": cleaned, "history": tracker.get_doi_history(cleaned)}

