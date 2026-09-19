"""API REST de Thinkuy (FastAPI) — Orquestador modular."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import config, db, profile
from . import auth
from .common import (
    _http,
)
from .routers import (
    admin,
    charting,
    editorial,
    feed,
    fulltext,
    graph,
    harvest,
    librarian,
    screening,
)
from .scheduler import build_scheduler

log = logging.getLogger("radar.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranque/cierre: init DB, scheduler opcional, cierre del cliente HTTP."""
    conn = db.connect()
    db.init_db(conn)
    db.rebuild_anchor_signals(conn)
    conn.close()
    sched = None
    if config.AUTO_HARVEST:
        sched = build_scheduler()
        sched.start()
        log.info("Scheduler automático iniciado (cada %dh)", config.HARVEST_INTERVAL_HOURS)
    try:
        yield
    finally:
        if sched:
            sched.shutdown(wait=False)
        _http.close()


app = FastAPI(
    title=f"Thinkuy API — {profile.field_profile.name}",
    description=f"Radar de comunicación científica para el campo «{profile.field_profile.name}».\n"
                "Filosofía: «No busques el paper. Deja que el paper te encuentre.»",
    version=config.VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------- Routers modulares
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(feed.router)
app.include_router(librarian.router)
app.include_router(screening.router)
app.include_router(charting.router)
app.include_router(harvest.router)
app.include_router(graph.router)
app.include_router(editorial.router)
app.include_router(fulltext.router)


# ---------------------------------------------------------------- Redirecciones y raíz
@app.get("/")
def root():
    return RedirectResponse("/app/")


@app.get("/widget")
def widget_redirect():
    return RedirectResponse("/app/widget.html")


# ---------------------------------------------------------------- PWA estática
class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


if config.PWA_DIR.exists():
    app.mount("/app", NoCacheStaticFiles(directory=str(config.PWA_DIR), html=True), name="pwa")

# ---------------------------------------------------------------- Re-exports para retrocompatibilidad
# Antes se copiaba a `globals()` TODO atributo público de cada router (incluidos imports
# accidentales). Ahora se re-exporta solo lo que consumidores externos (pruebas/scripts)
# usan de verdad: el endpoint de revisión sistemática y el módulo `live_search`.
from ..harvester import live_search  # noqa: F401  (retrocompatibilidad)
from .routers.screening import systematic_review_endpoint  # noqa: F401  (retrocompatibilidad)

build_fingerprint = admin.build_fingerprint