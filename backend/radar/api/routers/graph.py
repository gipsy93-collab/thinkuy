"""Subrouter de la API de Thinkuy."""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Response

from ... import citation_graph, config, controversy, db, deep_research, gaps, network, proximity, reports
from ...harvester import live_search
from ...matching import parse_keywords
from ..common import (
    _as_int,
    _as_list,
)

router = APIRouter(tags=['graph'])
log = logging.getLogger('radar.api.graph')


def _dois_de_protocolo(conn, protocol_id: int | None) -> list[str]:
    """DOIs de los artículos **incluidos** de un protocolo (corpus curado).

    Escuelas y Trayectoria deben calcularse sobre contenido curado, no sobre resultados crudos de
    la sonda: medido (22-09-2026), un corpus arbitrario produce escuelas de paleontología o
    bibliometría. Se descartan los DOI sintéticos (p. ej. `dialnet:...`), que no resuelven.
    """
    if not protocol_id:
        return []
    try:
        filas = db.list_screenings(conn, int(protocol_id), decision="included", limit=500)
    except Exception:
        return []
    salida: list[str] = []
    for s in filas:
        d = str(s.get("doi") or "").strip().lower()
        if d and not d.startswith("article:"):
            salida.append(d)
    return salida

@router.get("/api/graph/stats")
def graph_stats():
    conn = db.connect()
    try:
        st = citation_graph.citation_stats(conn)
        out = {k: v for k, v in st.items() if k not in ("top_indegree", "top_outdegree")}
        out["top_hubs"] = citation_graph.hubs(conn, limit=5)
        return out
    finally:
        conn.close()


@router.get("/api/graph/hubs")
def graph_hubs(limit: int = Query(10, ge=1, le=50)):
    conn = db.connect()
    try:
        return {"hubs": citation_graph.hubs(conn, limit=limit)}
    finally:
        conn.close()


@router.get("/api/graph/co-cited")
def graph_co_cited(
    doi: str,
    limit: int = Query(10, ge=1, le=30),
    mode: str = Query("auto", pattern="^(auto|local|live)$", description="auto (local con fallback en vivo), local, o live"),
):
    conn = db.connect()
    try:
        results = citation_graph.co_cited(conn, doi, limit=limit, mode=mode)
        return {"doi": doi, "mode": mode, "co_cited": results, "total": len(results)}
    finally:
        conn.close()


@router.get("/api/graph/schools")
def graph_schools(
    threshold: int = Query(2, ge=1, le=10, description="Umbral mínimo de co-citaciones compartidas"),
    min_size: int = Query(2, ge=2, le=20, description="Mínimo de nodos por escuela"),
    min_catalog: int = Query(3, ge=1, le=20, description="Mínimo de artículos EN EL CATÁLOGO por escuela (modo local)"),
    live: bool = Query(True, description="Construir el grafo del corpus EN VIVO (OpenAlex) en vez de usar solo el catálogo"),
    limit: int = Query(15, ge=1, le=50, description="Cantidad máxima de escuelas"),
    dois: Optional[List[str]] = Query(None, description="DOIs del corpus a analizar (opcional; tiene prioridad sobre protocol_id)"),
    protocol_id: Optional[int] = Query(None, description="Usar como corpus los artículos INCLUIDOS de este protocolo (contenido curado; recomendado)"),
):
    """Detecta 'Escuelas de Pensamiento' mediante clustering de co-citación (Union-Find).

    **Corpus**: por prioridad, `dois` explícitos; si no, los **incluidos** del `protocol_id`
    (contenido curado — recomendado); si no, el catálogo global. Con corpus, construye el grafo
    **en vivo** desde OpenAlex. Medido (22-09-2026): un corpus arbitrario produce escuelas de
    paleontología o bibliometría; debe usarse contenido curado.
    """
    conn = db.connect()
    try:
        corpus = list(dois) if dois else _dois_de_protocolo(conn, protocol_id)
        origen = "dois" if dois else ("protocolo" if corpus else "global")

        if corpus and live:
            try:
                gconn = citation_graph.build_live_graph(corpus)
                try:
                    schools = citation_graph.detect_cocitation_clusters(
                        gconn, threshold=threshold, min_size=min_size,
                        max_clusters=limit, min_catalog=1,
                    )
                    stats = citation_graph.citation_stats(gconn)
                finally:
                    gconn.close()
                return {
                    "total_schools": len(schools), "schools": schools, "scoped": True,
                    "origen_corpus": origen, "corpus_n": len(corpus),
                    "modo": "live", "corpus_resuelto": True, "fallback_global": False, "aviso": None,
                    "grafo": {"nodos": stats.get("nodes"), "aristas": stats.get("edges"),
                              "densidad": stats.get("density")},
                }
            except Exception as e:
                log.warning("Grafo en vivo (escuelas) falló: %s", e)

        aids = citation_graph.resolve_article_ids(conn, corpus) if corpus else None
        schools = citation_graph.detect_cocitation_clusters(
            conn, threshold=threshold, min_size=min_size, max_clusters=limit,
            article_ids=aids, min_catalog=min_catalog,
        )
        fallback_global = bool(corpus) and not aids
        return {
            "total_schools": len(schools),
            "schools": schools,
            "scoped": bool(corpus),
            "origen_corpus": origen,
            "corpus_n": len(corpus),
            "modo": "local",
            "corpus_resuelto": (not corpus) or bool(aids),
            "fallback_global": fallback_global,
            "aviso": ("El corpus no está en el catálogo: se analizó el catálogo GLOBAL."
                      if fallback_global else None),
        }
    finally:
        conn.close()


@router.get("/api/graph/main-path")
def graph_main_path(
    top_n: int = Query(20, ge=5, le=50, description="Número de transiciones principales"),
    live: bool = Query(True, description="Construir el grafo del corpus EN VIVO (OpenAlex) en vez de usar solo el catálogo"),
    dois: Optional[List[str]] = Query(None, description="DOIs del corpus a analizar (opcional; tiene prioridad sobre protocol_id)"),
    protocol_id: Optional[int] = Query(None, description="Usar como corpus los artículos INCLUIDOS de este protocolo (contenido curado; recomendado)"),
):
    """Calcula la Trayectoria Principal (Main Path Analysis) mediante Search Path Count (SPC).

    **Corpus**: `dois` explícitos, o los **incluidos** del `protocol_id` (curado), o el global.
    Con corpus, construye el grafo **en vivo** desde OpenAlex.
    """
    conn = db.connect()
    try:
        corpus = list(dois) if dois else _dois_de_protocolo(conn, protocol_id)
        origen = "dois" if dois else ("protocolo" if corpus else "global")

        if corpus and live:
            try:
                gconn = citation_graph.build_live_graph(corpus)
                try:
                    transitions = citation_graph.calculate_main_path(gconn, top_n=top_n)
                    stats = citation_graph.citation_stats(gconn)
                finally:
                    gconn.close()
                return {
                    "top_n": top_n, "main_path_transitions": transitions, "scoped": True,
                    "origen_corpus": origen, "corpus_n": len(corpus),
                    "modo": "live", "corpus_resuelto": True, "fallback_global": False, "aviso": None,
                    "grafo": {"nodos": stats.get("nodes"), "aristas": stats.get("edges"),
                              "densidad": stats.get("density")},
                }
            except Exception as e:
                log.warning("Grafo en vivo (SPC) falló: %s", e)

        aids = citation_graph.resolve_article_ids(conn, corpus) if corpus else None
        transitions = citation_graph.calculate_main_path(conn, top_n=top_n, article_ids=aids)
        fallback_global = bool(corpus) and not aids
        stats = citation_graph.citation_stats(conn)
        return {
            "top_n": top_n,
            "main_path_transitions": transitions,
            "scoped": bool(corpus),
            "origen_corpus": origen,
            "corpus_n": len(corpus),
            "modo": "local",
            "corpus_resuelto": (not corpus) or bool(aids),
            "fallback_global": fallback_global,
            "aviso": ("El corpus no está en el catálogo: se analizó el catálogo GLOBAL."
                      if fallback_global else None),
            # Tamaño del grafo sobre el que se calculó (para no presentar una base flaca como sólida).
            "grafo": {"nodos": stats.get("nodes"), "aristas": stats.get("edges"),
                      "densidad": stats.get("density")},
        }
    finally:
        conn.close()


@router.get("/api/graph/roles")
def graph_roles(
    dois: Optional[List[str]] = Query(None, description="Lista de DOIs específicos a categorizar"),
    limit: int = Query(50, ge=1, le=100, description="Límite para clasificación por defecto"),
):
    """Clasificación heurística de roles epistemológicos (Seminal, Empirical, Theoretical, Synthesis, Methodological)."""
    conn = db.connect()
    try:
        return {"roles": citation_graph.curate_roles(conn, dois=dois, limit=limit)}
    finally:
        conn.close()


@router.get("/api/graph/bridges")
def graph_bridges(
    cluster_a: List[str] = Query(..., description="DOIs de la Comunidad A"),
    cluster_b: List[str] = Query(..., description="DOIs de la Comunidad B"),
    limit: int = Query(15, ge=1, le=50),
):
    """Descubre artículos bisagra / puentes epistemológicos que conectan dos escuelas de pensamiento."""
    conn = db.connect()
    try:
        return {
            "bridges": citation_graph.find_epistemic_bridges(
                conn, cluster_a_dois=cluster_a, cluster_b_dois=cluster_b, limit=limit
            )
        }
    finally:
        conn.close()


@router.get("/api/graph/expand")
def graph_expand(
    doi: str = Query(..., description="DOI del paper semilla"),
    direction: str = Query("both", pattern="^(backward|forward|both)$", description="Dirección del snowballing"),
    limit: int = Query(25, ge=5, le=100),
):
    """Expansión de red (Snowballing backward/forward) con subgrafo de citaciones y roles epistemológicos."""
    conn = db.connect()
    try:
        res = citation_graph.expand_seed_graph(conn, seed_doi=doi, direction=direction, limit=limit)
        if "error" in res:
            raise HTTPException(404, res["error"])
        return res
    finally:
        conn.close()


@router.get("/api/graph/similar/{doi:path}")
def graph_similar(doi: str, limit: int = Query(15, ge=1, le=50)):
    """Similitud bibliográfica por Jaccard sobre referencias compartidas dentro del catálogo."""
    conn = db.connect()
    try:
        similar = citation_graph.get_similar_by_references(conn, doi=doi, limit=limit)
        return {"target_doi": doi, "count": len(similar), "similar_works": similar}
    finally:
        conn.close()


@router.get("/api/controversies")
def controversies(topic: str = Query(..., description="Tema o afirmación a analizar"),
                  limit: int = Query(15, ge=5, le=50)):
    conn = db.connect()
    try:
        return controversy.analyze_topic(conn, topic, limit=limit)
    finally:
        conn.close()


@router.get("/api/gaps")
def gaps_endpoint(limit: int = Query(8, ge=1, le=20)):
    conn = db.connect()
    try:
        return {
            "under_explored_pairs": gaps.under_explored_pairs(conn, limit=limit),
            "dense_without_synthesis": gaps.dense_without_synthesis(conn, limit=limit),
            "emerging_keywords": gaps.emerging_keywords(conn, limit=limit),
            "infra_cited": gaps.infra_cited(conn, limit=limit),
        }
    finally:
        conn.close()


@router.get("/api/questions")
def questions():
    conn = db.connect()
    try:
        return gaps.three_questions(conn)
    finally:
        conn.close()


@router.get("/api/network")
def network_view(min_works: int = Query(1, ge=1, le=10)):
    conn = db.connect()
    try:
        return network.full_network(conn, min_works=min_works)
    finally:
        conn.close()


@router.get("/api/network/export")
def network_export(format: str = Query("net", pattern="^(net|clu|vec)$"),
                   what: str = Query("sector", pattern="^(sector|community)$"),
                   field: str = Query("n"),
                   min_works: int = Query(1, ge=1, le=10)):
    """Exporta la red en formato Pajek: .net (vértices+líneas), .clu (partición), .vec (vector)."""
    conn = db.connect()
    try:
        net_data = network.full_network(conn, min_works=min_works)
        if format == "clu":
            text = network.export_clu(net_data, what)
            media = "text/plain; charset=utf-8"
            fname = f"thinkuy-network-{what}.clu"
        elif format == "vec":
            text = network.export_vec(net_data, field)
            media = "text/plain; charset=utf-8"
            fname = f"thinkuy-network-{field}.vec"
        else:
            text = network.export_net(net_data)
            media = "text/plain; charset=utf-8"
            fname = "thinkuy-network.net"
        return Response(content=text, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})
    finally:
        conn.close()


@router.get("/api/radar")
def radar_view(topic: str = Query("", description="Pregunta/tema en el centro"),
               doi: str = Query("", description="Artículo como centro (opcional)"),
               weights: str = Query("0.4,0.3,0.2,0.1", description="w_afinidad,w_conexion,w_actualidad,w_productividad"),
               limit: int = Query(25, ge=5, le=100),
               min_works: int = Query(1, ge=1, le=10),
               excluded: str = Query("", description="Autores a excluir (separados por coma)"),
               included: str = Query("", description="Autores a incluir (separados por coma)"),
               affinity_divisor: int = Query(proximity.AFFINITY_DIVISOR, ge=1, le=500,
                                             description="Divisor para escalar la afinidad temática"),
               productivity_constant: float = Query(proximity.PRODUCTIVITY_CONSTANT, ge=0.1, le=50.0,
                                                    description="Constante C en la fórmula n/(n+C)"),
               min_dist: float = Query(proximity.MIN_DIST, ge=1.0, le=50.0,
                                       description="Distancia mínima entre nodos en el layout"),
               recency_decay: str = Query(proximity.RECENCY_DECAY, pattern="^(linear|exponential)$",
                                          description="Modo de decaimiento de recencia: linear o exponential"),
               normalize_weights: bool = Query(proximity.NORMALIZE_MULTIPLEX_WEIGHTS,
                                               description="Normalizar pesos de capas multiplex a [0,1]")):
    """Radar de proximidad autoral: quién orbita la pregunta y quién conversa con quién."""
    conn = db.connect()
    try:
        excl_list = [x.strip() for x in excluded.split(",") if x.strip()] if excluded else None
        incl_list = [x.strip() for x in included.split(",") if x.strip()] if included else None
        return proximity.radar(conn, topic=topic or None, doi=doi or None,
                               weights=weights, limit=limit, min_works=min_works,
                               excluded=excl_list, included=incl_list,
                               affinity_divisor=affinity_divisor,
                               productivity_constant=productivity_constant,
                               min_dist=min_dist,
                               recency_decay=recency_decay,
                               normalize_weights=normalize_weights)
    finally:
        conn.close()


@router.post("/api/radar/discover")
def radar_discover(payload: dict = Body(...)):
    """Búsqueda activa y continua de nuevas publicaciones por tema en OpenAlex y Crossref.
    Guarda los artículos descubiertos, crea o reutiliza un ancla de vigilancia para el tema
    y devuelve el radar actualizado con los nuevos autores en órbita."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="El cuerpo debe ser un objeto JSON.")
    topic = str(payload.get("topic") or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="El campo 'topic' es obligatorio.")
    doi = str(payload.get("doi") or "").strip() or None
    days = _as_int(payload.get("days", 730), 730, 1, 3650)
    max_results = _as_int(payload.get("max_results", 30), 30, 1, 50)
    weights = str(payload.get("weights") or "0.4,0.3,0.2,0.1")
    limit = _as_int(payload.get("limit", 25), 25, 5, 100)
    min_works = _as_int(payload.get("min_works", 1), 1, 1, 10)
    affinity_divisor = _as_int(payload.get("affinity_divisor", proximity.AFFINITY_DIVISOR),
                               proximity.AFFINITY_DIVISOR, 1, 500)
    productivity_constant = float(payload.get("productivity_constant", proximity.PRODUCTIVITY_CONSTANT))
    productivity_constant = max(0.1, min(50.0, productivity_constant))
    min_dist = float(payload.get("min_dist", proximity.MIN_DIST))
    min_dist = max(1.0, min(50.0, min_dist))
    recency_decay = str(payload.get("recency_decay", proximity.RECENCY_DECAY))
    if recency_decay not in ("linear", "exponential"):
        recency_decay = proximity.RECENCY_DECAY
    normalize_weights = bool(payload.get("normalize_weights", proximity.NORMALIZE_MULTIPLEX_WEIGHTS))
    monitor = payload.get("watch", True)
    monitor = monitor if isinstance(monitor, bool) else str(monitor).strip().lower() not in ("0", "false", "no")

    conn = db.connect()
    try:
        disc_res = live_search.discover_by_topic(conn, topic=topic, days=days, max_results=max_results)
        watch_info = None
        if monitor:
            try:
                canonical = ", ".join(parse_keywords(topic)) or topic
                existing = next((w for w in db.watch_list(conn) if w.get("keywords") == canonical), None)
                if existing is None:
                    watch_info = db.watch_create(conn, canonical, f"Radar en vivo: {canonical}")
                else:
                    watch_info = existing
                watch_info = {**watch_info, "new": len(db.watch_new_articles(conn, watch_info, limit=20))}
            except Exception as exc:
                watch_info = {"error": str(exc)}

        radar_data = proximity.radar(conn, topic=topic, doi=doi, weights=weights, limit=limit,
                                     min_works=min_works,
                                     excluded=_as_list(payload.get("excluded")),
                                     included=_as_list(payload.get("included")),
                                     affinity_divisor=affinity_divisor,
                                     productivity_constant=productivity_constant,
                                     min_dist=min_dist,
                                     recency_decay=recency_decay,
                                     normalize_weights=normalize_weights)
        radar_data["discovery"] = disc_res
        radar_data["continuous_monitoring"] = {
            "watch": watch_info,
            "auto_harvest_enabled": config.AUTO_HARVEST,
            "auto_harvest_interval_hours": config.HARVEST_INTERVAL_HOURS,
        }
        return radar_data
    finally:
        conn.close()


@router.get("/api/deep-research")
def deep_research_endpoint(topic: str = Query(..., description="Pregunta de investigación"),
                           mode: str = Query("deterministic", pattern="^(deterministic|hybrid)$"),
                           limit: int = Query(20, ge=5, le=50)):
    """Informe en capas (estado de la conversación). deterministic = plantillas sobre
    fragmentos reales; hybrid = LLM restringido al evidence pack + post-check de anclaje."""
    conn = db.connect()
    try:
        return deep_research.deep_research(conn, topic, mode=mode, limit=limit)
    finally:
        conn.close()


@router.get("/api/report")
def report_markdown(topic: str = Query(..., description="Pregunta de investigación"),
                    limit: int = Query(20, ge=5, le=50)):
    """Informe en capas exportado a Markdown (descargable)."""
    conn = db.connect()
    try:
        rep = reports.layered_report(conn, topic, limit=limit)
        text = reports.report_markdown(rep)
        fname = "thinkuy-report.md"
        return Response(content=text, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})
    finally:
        conn.close()

