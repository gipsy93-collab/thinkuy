# -*- coding: utf-8 -*-
"""Análisis de grafo web, inlinks/outlinks, web twins y radar de proximidad."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .. import config
from ..normalize import unescape
from .common import (
    _IBERO_CC,
    _INDEXER_KW,
    _SPAM_TLDS,
    CC_DOMAIN_RANKS_DB,
    CC_INLINKS_DB,
    CC_RELEASE_ID,
    MEGA_HUB_DOMAINS,
    WEB_TWINS_RELEASE,
    _cc_total_domains,
    _clean_domain,
    _domain_candidates,
    _get_proximity_radius,
    _is_portal_host,
    _journal_identity_from_url,
    _n_es,
    _otras_citas_frase,
    _url_matches_scope,
    log,
)
from .commoncrawl import (
    get_cc_history_trajectory,
    get_real_referrers,
)


def build_conversational_web_graph_analysis(
    harmonic_data: Dict[str, Any],
    journal_title: str,
    domain: str,
    shared_host: bool = False,
    journal_segment: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Diagnóstico conversacional CALIBRADO del Web Graph.

    Principios de redacción (webmetría aplicada a comunicación científica):
      1. El lenguaje se ajusta a la posición REAL del dominio en el grafo: no hay prosa
         triunfal para dominios de la cola larga.
      2. Se declara siempre la unidad realmente medida (Common Crawl agrega a nivel de
         dominio registrable; para subdominios universitarios la cifra es de toda la
         institución, no de la revista).
      3. La Centralidad Armónica se explica por lo que es (cercanía estructural en el
         grafo de enlaces) y por lo que NO es (tráfico, citas, calidad editorial).
      4. No se fabrican interpretaciones causales ("bibliotecas enlazan directamente",
         "respaldo de repositorios de prestigio") que el indicador no permite verificar.
    """
    available = bool(harmonic_data.get("available"))
    attr = harmonic_data.get("attribution") or {}
    escalated = attr.get("level") == "escalated"
    measured = attr.get("matched") or harmonic_data.get("domain_matched") or domain
    queried = attr.get("queried") or domain

    if not available:
        status_msg = harmonic_data.get("status", "Dominio no disponible")
        return {
            "available": False,
            "headline": "Sin medición disponible en el Web Graph indexado",
            "tier_label": "Sin registro en el Web Graph",
            "percentile_top": None,
            "summary_paragraphs": [
                f"No hay medición disponible para el dominio consultado ({status_msg.lower()}).",
                "Cuando una revista no aparece en el ranking de dominios de Common Crawl puede deberse a un portal muy reciente, a directivas de robots.txt que excluyen el rastreo (CCBot) o simplemente a una conectividad entrante aún insuficiente para figurar en el corte del grafo. Es un dato sobre la web abierta, no un juicio sobre la calidad editorial.",
                "Pauta editorial: consolidar un subdominio canónico persistente, garantizar la indexabilidad del OJS (OAI-PMH, sitemaps) y fomentar enlaces desde portales establecidos (universidad, repositorios, prensa) es la vía más directa para entrar en el grafo.",
            ],
            "items_explanation": {
                "harmonic_rank": "Sin registro en este release del Web Graph: el dominio no figura en el corte primario del ranking de dominios.",
                "harmonic_val": "Sin valor registrado: no hay suficientes caminos cortos entrantes en el grafo para computar cercanía.",
                "pagerank_rank": "Sin registro: no hay respaldo medible de enlaces entrantes en este release.",
            },
        }

    rank = harmonic_data.get("harmonic_rank") or 0
    val = harmonic_data.get("harmonic_val") or 0.0
    pr_rank = harmonic_data.get("pagerank_rank") or 0
    pr_val = harmonic_data.get("pagerank_val") or 0.0
    total_domains = harmonic_data.get("total_domains") or _cc_total_domains(CC_DOMAIN_RANKS_DB) or 58_900_000
    total_txt = f"{total_domains / 1_000_000:.1f}M"

    percentile_top = round((rank / total_domains) * 100, 2) if rank > 0 else 0.01
    if percentile_top < 0.01:
        percentile_top = 0.01
    better_than = max(0.0, min(100.0 - percentile_top, 99.9))

    # ---- Calibración por tier: cada banda tiene SU propia lectura, sin prosa universal.
    if rank <= 10_000:
        tier_label = f"Élite de Conectividad Global (Top {percentile_top:.2f}%)"
        headline = "Nodo de máxima conectividad estructural en la web"
        tier_sentence = (
            "Está entre los nodos de mayor conectividad estructural del planeta: los caminos "
            "más cortos del grafo pasan cerca de él y su descubrimiento por navegación de "
            "enlaces es inmediato desde amplias regiones de la web."
        )
    elif rank <= 100_000:
        tier_label = f"Alta Conectividad Internacional (Top {percentile_top:.2f}%)"
        headline = "Dominio bien conectado en la web abierta"
        tier_sentence = (
            "Es un dominio bien conectado: se llega a él en pocos saltos desde amplias zonas "
            "del grafo, aunque no integra el núcleo de máxima visibilidad donde se sitúan "
            "los grandes portales mundiales."
        )
    elif rank <= 500_000:
        tier_label = f"Conectividad Sólida (Top {percentile_top:.2f}%)"
        headline = "Parte del cuerpo principal de la web abierta"
        tier_sentence = (
            "Forma parte del cuerpo principal de la web abierta: es alcanzable sin excesivos "
            "saltos y sostiene una presencia estructural sólida, aunque a varias distancias "
            "de los grandes ejes de navegación."
        )
    elif rank <= 2_000_000:
        tier_label = f"Conectividad Intermedia (Top {percentile_top:.2f}%)"
        headline = "Posición intermedia en el grafo de enlaces"
        tier_sentence = (
            "Se ubica en la franja intermedia del grafo: el dominio existe, es alcanzable y "
            "tiene enlaces entrantes, pero su posición estructural es modesta. Esta cifra no "
            "debería leerse como una visibilidad destacada, sino como una base desde la cual "
            "crecer."
        )
    else:
        tier_label = f"Cola Larga del Grafo (Top {percentile_top:.2f}%)"
        headline = "Periferia estructural del grafo de enlaces"
        tier_sentence = (
            "Opera en la periferia del grafo de enlaces: su conectividad entrante es limitada. "
            "En este rango las métricas estructurales son señales débiles: miden enlaces, no "
            "calidad ni impacto editorial, y el margen de mejora pasa por enlaces salientes "
            "desde dominios establecidos (universidad, repositorios, prensa, Wikipedia)."
        )

    val_millions = val / 1_000_000
    val_str = f"{val_millions:.2f} millones" if val_millions >= 1 else f"{val:,.0f}"

    # ---- Párrafo 1: unidad medida + posición calibrada
    escalation_txt = ""
    if escalated and measured and queried and measured.lower() != queried.lower():
        escalation_txt = (
            f" Nota de atribución: Common Crawl agrega las métricas a nivel de dominio "
            f"registrable, por lo que la cifra corresponde a '{measured}' — ancestro del "
            f"dominio consultado ('{queried}') — e incluye a toda la institución, no solo a "
            f"esta revista."
        )
    p1 = (
        f"¿Qué significa el puesto #{rank:,}? La cifra proviene del Web Graph oficial de "
        f"Common Crawl, que ordena más de {total_txt} dominios por su conectividad "
        f"estructural en el grafo de hipervínculos. El dominio realmente medido es "
        f"'{measured}'." + escalation_txt +
        f" Con ese puesto, el dominio está mejor conectado que aproximadamente el "
        f"{better_than:.1f}% de los dominios del grafo. {tier_sentence}"
    )

    # ---- Párrafo 2: el Valor Armónico, definido con precisión y con sus límites
    p2 = (
        f"El Valor Armónico ({val_str}) resume la cercanía estructural del dominio en el "
        f"grafo: para cada dominio de la web se toma su distancia en enlaces hasta "
        f"'{measured}' y se agrega la inversa de esas distancias; valores más altos "
        f"significan que, en promedio, la mayoría de los dominios está a pocos saltos. Es "
        f"una medida de la topología de enlaces, no del comportamiento de las personas: no "
        f"mide tráfico de lectores, citas académicas ni calidad editorial."
    )

    # ---- Párrafo 3: comparación HC vs PageRank, calibrada por rango
    long_tail = 2_000_000
    pr_missing = not pr_rank or pr_rank <= 0
    if rank > long_tail and (pr_missing or pr_rank > long_tail):
        comp_nuance = (
            f"Tanto la Centralidad Armónica (#{rank:,}) como el PageRank "
            f"(#{pr_rank:,} si está disponible) caen en la cola larga del grafo. En ese "
            f"rango los dos indicadores casi no discriminan: diferencias de cientos de "
            f"miles de puestos reflejan ruido estructural, no jerarquías reales. La lectura "
            f"correcta es de conjunto —conectividad limitada en la web abierta— y la palanca "
            f"editorial no está en comparar métricas entre sí, sino en conseguir enlaces "
            f"desde dominios establecidos."
        )
    elif pr_missing:
        comp_nuance = (
            "El PageRank no está registrado en este release para el dominio analizado: no "
            "hay respaldo medible de enlaces entrantes de alta autoridad. La Centralidad "
            "Armónica disponible debe leerse como señal de cercanía, no de prestigio."
        )
    elif rank < pr_rank:
        comp_nuance = (
            f"La Centralidad Armónica (#{rank:,}) va por delante del PageRank "
            f"(#{pr_rank:,}): el dominio es más alcanzable desde muchos puntos del grafo de "
            f"lo que sugiere la autoridad de los dominios que lo enlazan. Es el patrón "
            f"habitual de redes académicas y regionales —muchos enlaces de cercanía "
            f"(repositorios, portales hermanos) y menos desde dominios de máxima "
            f"autoridad—. Si el objetivo editorial es ganar autoridad, el apalancamiento "
            f"está en enlaces desde portales consolidados."
        )
    elif rank > pr_rank:
        comp_nuance = (
            f"El PageRank (#{pr_rank:,}) va por delante de la Centralidad Armónica "
            f"(#{rank:,}): los dominios que lo enlazan tienden a tener más autoridad de lo "
            f"que su cercanía global sugiere. Es el patrón de respaldo concentrado —pocos "
            f"pero influyentes remitentes—; su alcance por cercanía en el grafo es, sin "
            f"embargo, menor."
        )
    else:
        comp_nuance = (
            f"Ambos indicadores se sitúan en un rango comparable (HC #{rank:,}, PR "
            f"#{pr_rank:,}): equilibrio entre cercanía en el grafo y autoridad de los "
            f"enlaces entrantes, sin señales extremas en ninguna dirección."
        )

    paragraphs = [p1, p2, comp_nuance]

    if shared_host:
        paragraphs.append(
            f"Lectura editorial clave: la unidad medida es '{measured}', un dominio "
            f"compartido que aloja a varias revistas (entre ellas '{journal_title}'). Esta "
            f"métrica funciona como techo de referencia colectivo del portal o de la "
            f"institución; no debe presentarse como la medición de la revista en particular."
        )

    return {
        "available": True,
        "headline": headline,
        "tier_label": tier_label,
        "percentile_top": percentile_top,
        "harmonic_rank": rank,
        "harmonic_val": val,
        "pagerank_rank": pr_rank,
        "pagerank_val": pr_val,
        "domain_analyzed": measured,
        "attribution": attr or None,
        "summary_paragraphs": paragraphs,
        "items_explanation": {
            "harmonic_rank": f"Posición #{rank:,} entre {total_txt} de dominios (mejor conectado que ~{better_than:.1f}% del grafo).",
            "harmonic_val": f"Cercanía estructural en el grafo de enlaces ({val_str}). No mide tráfico, citas ni calidad.",
            "pagerank_rank": f"Posición #{pr_rank:,} en PageRank: autoridad de los dominios que enlazan a '{measured}'.",
        },
    }


def build_web_proximity_radar(
    harmonic_data: Optional[Dict[str, Any]],
    journal_title: str,
    domain: str,
    competitors: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Construye la proyección polar (Radar Cibermétrico de Proximidad) en el Web Graph
    de Common Crawl.

    El centro (0, 0) representa el Epicentro / Núcleo de máxima hiperconectividad mundial
    (Top 10.000, e.g. Wikipedia, Google, grandes universidades).
    La distancia radial 'r' (0 a 1) mapea logarítmicamente la Centralidad Armónica
    (menor rango = menor número de saltos de enlace hacia el resto de la web).
    """

    rank = (harmonic_data or {}).get("harmonic_rank")
    val = (harmonic_data or {}).get("harmonic_val")
    total_domains = (harmonic_data or {}).get("total_domains") or _cc_total_domains(CC_DOMAIN_RANKS_DB) or 58_900_000
    total_txt = f"{total_domains / 1_000_000:.1f}M"

    def _get_radius(r_rank: Optional[int]) -> float:
        return _get_proximity_radius(r_rank, total_domains)

    target_radius = _get_radius(rank)

    if rank and rank > 0:
        pct_top = round((rank / total_domains) * 100, 2)
        if pct_top < 0.01:
            pct_top = 0.01
        distance_label = f"Rango #{rank:,} de {total_txt} dominios del Web Graph (Top {pct_top:.2f}%)"
        if rank <= 10_000:
            orbit_id = 1
            orbit_name = "Núcleo / Epicentro Global"
            orbit_badge = "Núcleo"
            orbit_desc = "Núcleo de máxima conectividad estructural: desde aquí el dominio es alcanzable en muy pocos saltos desde casi cualquier punto del grafo."
            ai_impact = "El dominio está en el núcleo mejor conectado del grafo: la probabilidad de presencia en corpus de rastreo es alta. Aun así, la prioridad de cada rastreador (CCBot, GPTBot, ClaudeBot) no es pública y depende de robots.txt, sitemaps y de la calidad técnica del sitio; no existe una garantía formal."
        elif rank <= 100_000:
            orbit_id = 2
            orbit_name = "Órbita 1: Alta Conectividad Internacional"
            orbit_badge = "Alta Conectividad"
            orbit_desc = "Alta conectividad estructural: alcanzable en pocos saltos desde amplias regiones de la web, aunque fuera del núcleo de máxima visibilidad."
            ai_impact = "Conectividad alta: el dominio es estructuralmente muy accesible, lo que favorece su rastreo e inclusión en corpus de entrenamiento. La prioridad concreta de cada proveedor no es pública; robots.txt y sitemaps siguen siendo los factores controlables."
        elif rank <= 500_000:
            orbit_id = 3
            orbit_name = "Órbita 2: Cuerpo Principal de la Web"
            orbit_badge = "Cuerpo Principal"
            orbit_desc = "Cuerpo principal de la web: presencia estructural sólida y accesible, a varias distancias de los ejes centrales de difusión."
            ai_impact = "Conectividad sólida: el dominio es rastreable y puede estar presente en corpus de entrenamiento. La prioridad de rastreo no es automática ni está garantizada por el rango; depende de robots.txt, sitemaps y de los enlaces entrantes."
        elif rank <= 2_000_000:
            orbit_id = 4
            orbit_name = "Órbita 3: Conectividad Intermedia"
            orbit_badge = "Conectividad Intermedia"
            orbit_desc = "Posición estructural intermedia: el dominio tiene enlaces entrantes, pero opera lejos de los ejes centrales de difusión y su conectividad es modesta en términos absolutos."
            ai_impact = "Posición intermedia: el dominio es alcanzable, pero está lejos de los ejes centrales. La inclusión en corpus de IA no está garantizada por esta posición; las palancas controlables son un robots.txt abierto, sitemaps y enlaces desde portales consolidados."
        else:
            orbit_id = 5
            orbit_name = "Órbita 4: Periferia del Grafo"
            orbit_badge = "Periferia"
            orbit_desc = "Periferia del grafo: conectividad entrante limitada. En este rango la métrica es una señal débil; la mejora depende de enlaces desde dominios establecidos."
            ai_impact = "Periferia del grafo: la probabilidad de presencia en corpus de entrenamiento es baja y la prioridad de rastreo menor. Las acciones efectivas son abrir robots.txt, publicar sitemaps y ganar enlaces desde dominios de autoridad."
    else:
        orbit_id = 5
        orbit_name = "Sin registro en el Web Graph"
        orbit_badge = "Sin dato"
        distance_label = "El dominio no figura en el corte primario de dominios del Web Graph"
        orbit_desc = "Sin registro de conectividad estructural en este release de Common Crawl."
        ai_impact = "Sin registro de conectividad: la inclusión en corpus de entrenamiento depende de un robots.txt abierto, sitemaps y enlaces entrantes; la posición no puede evaluarse."

    attr = (harmonic_data or {}).get("attribution") or {}
    measured = attr.get("matched") or (harmonic_data or {}).get("domain_matched") or domain
    measured_note = ""
    if attr.get("level") == "escalated" and measured and measured.lower() != (domain or "").lower():
        measured_note = (
            f"La posición corresponde al dominio registrable '{measured}' (ancestro de '{domain}', "
            f"que incluye a toda la institución), no solo a la revista consultada."
        )

    blips = [
        {
            "id": "target",
            "label": journal_title,
            "domain": domain,
            "rank": rank,
            "radius": round(target_radius, 3),
            "angle": 315,
            "is_target": True,
            "type": "target",
        },
        {
            "id": "wikipedia",
            "label": "Wikipedia (Núcleo)",
            "domain": "wikipedia.org",
            "rank": 5,
            "radius": round(_get_radius(5), 3),
            "angle": 210,
            "is_target": False,
            "type": "core_reference",
        }
    ]

    if competitors:
        angles = [120, 30, 165, 270]
        c_idx = 0
        for comp in competitors:
            c_rank = comp.get("harmonic_rank")
            c_title = comp.get("journal_title") or ""
            if c_rank and not comp.get("is_target"):
                blips.append({
                    "id": f"comp_{c_idx}",
                    "label": c_title[:24] + ("..." if len(c_title) > 24 else ""),
                    "domain": comp.get("domain") or "",
                    "rank": c_rank,
                    "radius": round(_get_radius(c_rank), 3),
                    "angle": angles[c_idx % len(angles)],
                    "is_target": False,
                    "type": "competitor",
                })
                c_idx += 1
                if c_idx >= 3:
                    break

    return {
        "available": bool(rank and rank > 0),
        "rank": rank,
        "harmonic_val": val,
        "total_domains": total_domains,
        "target_radius": round(target_radius, 3),
        "orbit_id": orbit_id,
        "orbit_name": orbit_name,
        "orbit_badge": orbit_badge,
        "distance_label": distance_label,
        "orbit_desc": orbit_desc,
        "ai_impact": ai_impact,
        "measured": measured,
        "measured_note": measured_note,
        "blips": blips,
        "rings": [
            {"id": "core", "radius": 0.25, "label": "Núcleo (<10k)", "color": "rgba(255, 209, 102, 0.35)"},
            {"id": "orbit1", "radius": 0.48, "label": "Alta Conectividad (<100k)", "color": "rgba(6, 214, 160, 0.3)"},
            {"id": "orbit2", "radius": 0.70, "label": "Cuerpo Principal (<500k)", "color": "rgba(17, 138, 178, 0.3)"},
            {"id": "orbit3", "radius": 0.88, "label": "Intermedia (<2M)", "color": "rgba(131, 56, 236, 0.3)"},
            {"id": "orbit4", "radius": 0.96, "label": "Periferia (>2M)", "color": "rgba(239, 71, 111, 0.3)"},
        ],
    }


def compute_web_twins(domain: str, our_pagerank_rank: Optional[int] = None,
                      neighbors_limit: int = 10, gap_min_hits: int = 2) -> Dict[str, Any]:
    """Gemelos web (embedding de hosts de Common Crawl) + brecha de enlaces.

    Lee la caché local construida por tools/web_twins_build.py (WEB_TWINS_DB) y
    cruza con los in-links reales (CC_INLINKS_DB) para hallar hubs que enlazan a
    varios gemelos pero NO a este dominio: adquisición legítima, no intercambio.
    """
    clean_dom = _clean_domain(domain) if domain else ""
    twins_db = str(config.DATA_DIR / "web_twins.db")
    if not clean_dom or clean_dom == "n/d" or not os.path.exists(twins_db):
        return {"available": False, "status": "Caché de gemelos web no disponible (correr tools/web_twins_build.py).", "neighbors": [], "link_gap": []}
    candidates = _domain_candidates(clean_dom)
    try:
        tc = sqlite3.connect(twins_db)
        tc.row_factory = sqlite3.Row
        matched_host = None
        neighbor_rows = []
        for cand in candidates:
            for probe in (cand, f"www.{cand}"):
                rs = tc.execute(
                    "SELECT neighbor_host, neighbor_domain, cosine, k_rank FROM hosts WHERE host = ? ORDER BY k_rank LIMIT ?",
                    (probe, neighbors_limit),
                ).fetchall()
                if rs:
                    matched_host, neighbor_rows = probe, rs
                    break
            if neighbor_rows:
                break
        tc.close()
        if not neighbor_rows:
            return {"available": False, "status": "Host fuera de la caché de gemelos: correr tools/web_twins_build.py incluyendo este dominio.", "neighbors": [], "link_gap": []}

        neighbors = []
        # "Mismo sitio" = el vecino es otra puerta de TU edificio: su dominio
        # registrable coincide con la raíz del host consultado (p. ej. al buscar
        # infonomy.scimagoepi.com, www.scimagoepi.com es "tu propio sitio", no un par).
        own_root = (candidates[-1] if candidates else clean_dom).lower()
        for r in neighbor_rows:
            nd = (r["neighbor_domain"] or "").lower()
            nh = (r["neighbor_host"] or "").lower()
            same_site = bool(nd) and (nd == own_root or nh == own_root or nh.endswith("." + own_root))
            neighbors.append({"host": r["neighbor_host"], "domain": r["neighbor_domain"],
                              "cosine": round(r["cosine"], 4), "k_rank": r["k_rank"], "same_site": same_site})
        neighbors.sort(key=lambda x: x["same_site"])

        ic = sqlite3.connect(CC_INLINKS_DB)
        try:
            ours: set = set()
            for cand in candidates:
                for (h,) in ic.execute("SELECT DISTINCT referrer_domain_norm FROM cc_inlinks WHERE target_domain_norm = ?", (cand,)):
                    ours.add(h)
            own_domains = {c.lower() for c in candidates} | {clean_dom.lower()}
            hub_to_neighbors: Dict[str, list] = {}
            for n in neighbors:
                nd = (n["domain"] or "").lower()
                if not nd or n.get("same_site"):
                    continue
                got = [h for (h,) in ic.execute("SELECT DISTINCT referrer_domain_norm FROM cc_inlinks WHERE target_domain_norm = ?", (nd,))]
                n["inlinks_computed"] = bool(got)
                for h in got:
                    hl = h.lower()
                    if hl in own_domains or hl == nd or hl == n["host"].lower() or hl in MEGA_HUB_DOMAINS:
                        continue
                    if any(hl.endswith(t) for t in _SPAM_TLDS):
                        continue
                    hub_to_neighbors.setdefault(h, []).append(nd)
            gap_all = sorted(((h, len(set(doms))) for h, doms in hub_to_neighbors.items()
                              if len(set(doms)) >= gap_min_hits and h not in ours),
                             key=lambda x: -x[1])
            # Clasificación de accionabilidad: un hub solo se recomienda si es de la
            # región iberoamericana (mismo ecosistema de indexación/idioma) o si es
            # infraestructura de visibilidad reconocida. El resto (p. ej. portales de
            # Tailandia que comparten "plomería OJS" con tus gemelos) se oculta
            # declarándolo: en revistas académicas, la similitud de enlaces mide
            # infraestructura compartida, no audiencia.
            def _clase(hub: str) -> str:
                hl = hub.lower()
                if any(hl.endswith(cc) for cc in _IBERO_CC):
                    return "region"
                if any(kw in hl for kw in _INDEXER_KW):
                    return "indexacion"
                return "global"
            gap = [(h, c, _clase(h)) for h, c in gap_all if _clase(h) != "global"][:8]
            ocultos = sum(1 for h, c in gap_all if _clase(h) == "global")
        finally:
            ic.close()

        if our_pagerank_rank:
            try:
                rc = sqlite3.connect(CC_DOMAIN_RANKS_DB)
                rc.row_factory = sqlite3.Row
                for n in neighbors:
                    if n.get("same_site"):
                        n["anchor"] = False
                        continue
                    row = rc.execute("SELECT pagerank_rank FROM cc_ranks WHERE domain_norm = ? LIMIT 1", (n["domain"],)).fetchone()
                    if row and row["pagerank_rank"]:
                        n["pagerank_rank"] = int(row["pagerank_rank"])
                        n["anchor"] = int(row["pagerank_rank"]) < int(our_pagerank_rank)
                    else:
                        n["anchor"] = False
                rc.close()
            except Exception:
                pass

        return {
            "available": True,
            "status": f"Gemelos web: vecindario estructural del host en el embedding de enlaces de Common Crawl (release {WEB_TWINS_RELEASE}).",
            "matched_host": matched_host,
            "attribution_level": "exact" if matched_host == clean_dom else "escalated",
            "release": WEB_TWINS_RELEASE,
            "neighbors": neighbors,
            "link_gap": [{"domain": h, "twins_linked": c, "clase": k} for h, c, k in gap],
            "link_gap_hidden_globales": ocultos,
            "map_view_url": "https://commoncrawl-web-graph-embeddings.static.hf.space/",
            "map_search_host": matched_host,
            "knn_space_url": "https://commoncrawl-web-graph-knn.hf.space/",
        }
    except Exception as e:
        log.warning("Error computando gemelos web para %s: %s", clean_dom, e)
        return {"available": False, "status": f"Error en gemelos web: {e}", "neighbors": [], "link_gap": []}


def discover_transmedia_channels(journal_title: str, journal_segment: Optional[str] = None, timeout: int = 4) -> List[Dict[str, Any]]:
    """
    Rastrea y verifica canales oficiales de divulgación transmedia (Substack, blogs)
    asociados a la revista, usando coincidencias semánticas y sondas a feeds RSS.
    """
    import xml.etree.ElementTree as ET
    found = []
    seen_urls = set()

    # 1. Feeds preconfigurados
    try:
        from . import tracker
        for pub_name, feed_url in getattr(tracker, "TRANSMEDIA_FEEDS", []):
            if journal_title and (journal_title.lower() in pub_name.lower() or pub_name.lower() in journal_title.lower()):
                seen_urls.add(feed_url)
                found.append({
                    "platform": "Substack" if "substack" in feed_url else "Blog Científico",
                    "source": pub_name,
                    "title": f"Canal oficial de divulgación: {pub_name}",
                    "url": feed_url.replace("/feed", ""),
                    "feed_url": feed_url,
                    "type": "Canal Asociado",
                    "posts": []
                })
    except Exception:
        pass

    # 2. Sonda heurística a Substack
    if not journal_title:
        return found

    stop_words = {'revista', 'revistas', 'journal', 'cuadernos', 'boletin', 'anales', 'acta', 'estudios', 'de', 'del', 'la', 'el', 'los', 'las', 'en', 'y', 'para', 'por'}
    raw_slug = re.sub(r'[^a-z0-9]', '', (journal_segment or '').lower())
    clean_title = re.sub(r'[^a-z0-9\s]', '', journal_title.lower())
    title_words = [w for w in clean_title.split() if w not in stop_words]
    title_slug = ''.join(title_words)

    candidate_slugs = []
    if title_slug:
        candidate_slugs.extend([f"revista{title_slug}", title_slug, f"rev{title_slug}"])
    if raw_slug and raw_slug not in candidate_slugs:
        candidate_slugs.extend([f"revista{raw_slug}", raw_slug, f"rev{raw_slug}"])

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for slug in candidate_slugs:
        feed_url = f"https://{slug}.substack.com/feed"
        if feed_url in seen_urls:
            continue
        seen_urls.add(feed_url)
        try:
            req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                if r.status == 200:
                    xml_data = r.read()
                    root = ET.fromstring(xml_data)
                    channel = root.find('channel')
                    if channel is None:
                        continue
                    c_title = (channel.find('title').text if channel.find('title') is not None else '') or slug
                    c_link = (channel.find('link').text if channel.find('link') is not None else '') or f"https://{slug}.substack.com"
                    c_desc = (channel.find('description').text if channel.find('description') is not None else '') or ''

                    combined = (c_title + ' ' + c_desc).lower()
                    if title_words:
                        matches = sum(1 for w in title_words if w in combined)
                        if matches < max(1, len(title_words) // 2) and journal_title.lower() not in combined:
                            continue

                    posts = []
                    for it in channel.findall('item')[:5]:
                        p_title = (it.find('title').text if it.find('title') is not None else '') or ''
                        p_link = (it.find('link').text if it.find('link') is not None else '') or ''
                        p_date = (it.find('pubDate').text if it.find('pubDate') is not None else '') or ''
                        if p_title:
                            posts.append({'title': p_title, 'url': p_link, 'pub_date': p_date})

                    found.append({
                        "platform": "Substack",
                        "source": c_title,
                        "title": f"Canal de divulgación en Substack: {c_title}",
                        "url": c_link,
                        "feed_url": feed_url,
                        "description": c_desc,
                        "posts": posts,
                        "type": "Canal Oficial de Divulgación"
                    })
                    break
        except Exception:
            continue

    # 3. Sonda heurística a LinkedIn (Página oficial de empresa / organización académica)
    clean_li = re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚñÑ0-9\s-]', '', journal_title.lower()).strip()
    li_words = [w for w in clean_li.split() if w]
    li_candidates = []
    if li_words and li_words[0] != 'revista':
        li_candidates.append("revista-" + "-".join(li_words))
    li_candidates.append("-".join(li_words))
    if journal_segment:
        li_candidates.append(f"revista-{journal_segment.lower()}")
        li_candidates.append(journal_segment.lower())

    seen_li = set()
    for lic in li_candidates:
        if lic in seen_li:
            continue
        seen_li.add(lic)
        encoded_slug = urllib.parse.quote(lic)
        li_url = f"https://www.linkedin.com/company/{encoded_slug}/"
        try:
            req = urllib.request.Request(li_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                if r.status == 200:
                    html = r.read().decode("utf-8", errors="ignore")
                    titles = re.findall(r'<title>([^<]+)</title>', html, re.IGNORECASE)
                    page_title = titles[0].replace('| LinkedIn', '').strip() if titles else journal_title
                    if any(w in page_title.lower() for w in li_words if len(w) > 3):
                        found.append({
                            "platform": "LinkedIn",
                            "source": page_title,
                            "title": f"Página oficial en LinkedIn: {page_title}",
                            "url": li_url,
                            "type": "Red Profesional"
                        })
                        break
        except Exception:
            continue

    return found


def audit_in_out_links(
    domain: str,
    journal_title: str,
    harmonic_data: Optional[Dict[str, Any]] = None,
    openalex_meta: Optional[Dict[str, Any]] = None,
    journal_segment: Optional[str] = None,
    shared_host_catalog: bool = False,
) -> Dict[str, Any]:
    """
    Audita los enlaces entrantes (In-Links: Wikipedia, Substack/Blogs, OpenAlex)
    y salientes (Out-Links: Zenodo, GitHub, DOIs, universidades) de la revista.
    Genera además la serie histórica del Web Graph y el diagnóstico consultivo para la UCC+I.

    Si se indica `journal_segment` (identidad de la revista dentro de un portal OJS compartido),
    las citas de Wikipedia se filtran a ese alcance: nunca se atribuyen a la revista las citas
    de revistas vecinas del mismo host.
    """
    clean_dom = _clean_domain(domain)

    ctx = ssl._create_unverified_context()

    # Evidencia de portal compartido (inicializada antes del bloque de Wikipedia).
    host_shared_evidence = shared_host_catalog or _is_portal_host(clean_dom)

    # ---------------- 1. IN-LINKS: Wikipedia en vivo (filtrado por alcance de revista)
    wiki_articles = []
    wiki_note = None
    host_items: List[Dict[str, Any]] = []
    if clean_dom and clean_dom != "n/d":
        host_items = []
        for lang in ("es", "en"):
            wiki_url = f"https://{lang}.wikipedia.org/w/api.php?action=query&list=exturlusage&euquery={urllib.parse.quote(clean_dom)}&eunamespace=0&eulimit=20&format=json"
            req = urllib.request.Request(wiki_url, headers={"User-Agent": "Thinkuy-UCC/1.0 (info@thinkuy.org)"})
            try:
                with urllib.request.urlopen(req, timeout=4, context=ctx) as r:
                    wdata = json.loads(r.read().decode("utf-8"))
                    items = wdata.get("query", {}).get("exturlusage", [])
                    for it in items:
                        title = it.get("title", "")
                        if title and not any(a["title"] == title for a in host_items):
                            host_items.append({
                                "title": title,
                                "lang": lang,
                                "wiki_url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                                "target_url": it.get("url", ""),
                            })
                    if len(host_items) >= 20:
                        break
            except Exception as e:
                log.debug("Error consultando Wikipedia (%s) para %s: %s", lang, clean_dom, e)

        if not host_items:
            wiki_articles = []
            wiki_note = None
            host_shared_evidence = shared_host_catalog or _is_portal_host(clean_dom)
        elif journal_segment:
            ojs_identities = {_journal_identity_from_url(a["target_url"]) for a in host_items} - {None}
            # Portal compartido: evidencia de catálogo + hostname tipo portal + varias identidades OJS.
            host_shared_evidence = shared_host_catalog or _is_portal_host(clean_dom) or len(ojs_identities) > 1
            if host_shared_evidence:
                scope_items = [a for a in host_items if _url_matches_scope(a["target_url"], journal_segment)]
                if scope_items:
                    wiki_articles = scope_items
                    otras = max(0, len(host_items) - len(scope_items))
                    wiki_note = (
                        f"Citas filtradas al alcance '{journal_segment}' de la revista dentro del portal "
                        f"compartido ({len(host_items)} cita(s) totales del host, de las cuales {otras} "
                        f"corresponden a otras revistas del portal)."
                    )
                else:
                    wiki_articles = []
                    other = ", ".join(sorted(ojs_identities)) or "otras revistas del portal"
                    wiki_note = (
                        f"Sin citas directas a '{journal_segment}' en Wikipedia. El host es un portal "
                        f"compartido: las {len(host_items)} cita(s) detectadas apuntan a otras revistas ({other})."
                    )
            else:
                # Host monorevista (dominio propio o subdominio dedicado): todas las citas le pertenecen.
                wiki_articles = host_items
                wiki_note = None
        else:
            ojs_identities = {_journal_identity_from_url(a["target_url"]) for a in host_items} - {None}
            host_shared_evidence = shared_host_catalog or _is_portal_host(clean_dom) or len(ojs_identities) > 1
            wiki_articles = host_items
            wiki_note = None
            if host_shared_evidence:
                wiki_note = (
                    "El host aloja varias revistas (portal compartido): estas citas son a nivel de "
                    "portal, no atribuibles a una revista concreta."
                )

    # ---- Hallazgo de ecosistema: la revista no trabaja sola (portal compartido).
    # Cuando el host es compartido, parte de las citas y de la conectividad estructural del
    # dominio provienen de OTRAS revistas del portal: es un activo colectivo, no de la revista
    # aislada, y debe presentarse como contexto del diagnóstico.
    host_ecosystem = {
        "shared": host_shared_evidence,
        "host_total_wikipedia_citations": len(host_items),
        "journal_wikipedia_citations": len(wiki_articles),
        "other_journals_citations": 0,
        "other_journals": [],
    }
    if host_items and host_shared_evidence:
        others = {_journal_identity_from_url(a["target_url"]) for a in host_items} - {None}
        if journal_segment:
            others.discard(journal_segment)
        host_ecosystem["other_journals"] = sorted(o for o in others if o)
        host_ecosystem["other_journals_citations"] = max(0, len(host_items) - len(wiki_articles))

    # ---------------- 1b. IN-LINKS: Menciones en Substack y Blogs de Divulgación
    blog_mentions = []
    try:
        blog_mentions = discover_transmedia_channels(journal_title, journal_segment=journal_segment)
    except Exception as e:
        log.debug("Error verificando blogs transmedia: %s", e)

    # ---------------- 2. OUT-LINKS: Sonda spider rápida al portal (portada + crawl 1-hop del menú informativo)
    outlinks_raw = []
    scanned_url = None
    pages_scanned = []

    TECHNICAL_NOISE_HOSTS = ("gmpg.org", "fonts.googleapis.com", "fonts.gstatic.com", "w3.org", "themeisle.com", "wordpress.org", "automattic.com", "gravatar.com")
    TECHNICAL_EXTS = (".css", ".js", ".woff", ".woff2", ".ttf", ".eot", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".ico")

    def _fetch_page(url: str) -> str:
        req_dom = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        with urllib.request.urlopen(req_dom, timeout=4, context=ctx) as r:
            return r.read().decode("utf-8", errors="ignore")

    def _external_hrefs(html: str, base_url: str) -> list:
        # Extracción de hipervínculos reales <a> (no <link> de fuentes, css o perfiles semánticos)
        raw_hrefs = re.findall(r'<a\b[^>]*?\bhref=["\']([^"\'>\s]+)["\']', html, re.IGNORECASE)
        resolved = []
        for href in raw_hrefs:
            h = unescape(href.strip())
            if h.startswith(("#", "mailto:", "javascript:", "tel:", "data:")):
                continue
            if h.startswith("//"):
                h = "https:" + h
            elif not h.startswith(("http://", "https://")):
                h = urllib.parse.urljoin(base_url, h)
            parsed = urllib.parse.urlparse(h)
            host = parsed.netloc.lower()
            path = parsed.path.lower()
            if not host or clean_dom in host:
                continue
            if any(nh in host for nh in TECHNICAL_NOISE_HOSTS):
                continue
            if path.endswith(TECHNICAL_EXTS):
                continue
            resolved.append(h)
        return list(dict.fromkeys(resolved))

    if clean_dom and clean_dom != "n/d":
        candidates = []
        # En portales compartidos, escanear primero la PORTADA DE LA REVISTA (con scope),
        # no la raíz del portal: los out-links de la raíz no son de la revista.
        if journal_segment:
            candidates.append(f"https://{clean_dom}/index.php/{journal_segment}/")
        candidates += [f"https://www.{clean_dom}/", f"https://{clean_dom}/", f"http://{clean_dom}/"]
        portal_html = ""
        for cand in candidates:
            try:
                html = _fetch_page(cand)
                scanned_url = cand
                portal_html = html
                outlinks_raw = _external_hrefs(html, cand)
                pages_scanned.append(cand)
                if outlinks_raw:
                    break
            except Exception:
                continue

        # Crawl 1-hop: los bloques de indexación/redes/aliados suelen vivir en páginas
        # informativas del menú (/es/indexacion, /about), no en la portada del OJS.
        # OJS usa dos formas de ruta: /index.php/<seg>/... o la corta /<seg>/... — admitirlas ambas.
        if portal_html and journal_segment:
            seg_l = journal_segment.lower().strip("/")
            roots = (f"/index.php/{seg_l}/", f"/{seg_l}/")
            SKIP_SEG = ("/issue", "/article", "catalog", "/download", "/user", "/submission",
                        "/search", "/login", "/register", "/query", "/editor", "/submission")
            NAV_KW = ("indexacion", "indexing", "indexada", "sobre", "about", "quien", "quienes",
                      "nosotros", "equipo", "contacto", "instituci", "politica", "policy",
                      "declaracion", "etica", "comite", "consejo", "mision", "vision",
                      "presencia", "repositorio", "enlace", "aliados")
            scanned_norm = {urllib.parse.urlsplit(p).path.lower().rstrip("/") for p in pages_scanned}
            hrefs = re.findall(r'<a\b[^>]*?\bhref=["\']([^"\'>\s]+)["\']', portal_html, re.IGNORECASE)
            internal: list = []
            for href in hrefs:
                h = unescape(href.strip())
                if h.startswith(("#", "mailto:", "javascript:", "tel:", "data:")):
                    continue
                u = urllib.parse.urljoin(scanned_url, h).split("#")[0]
                p = urllib.parse.urlsplit(u)
                host_l = (p.netloc or "").lower().replace("www.", "")
                path_l = (p.path or "/").lower()
                if host_l != clean_dom.lower().replace("www.", "") or not path_l.startswith(roots):
                    continue
                if any(s in path_l for s in SKIP_SEG):
                    continue
                if path_l.rstrip("/") in scanned_norm:
                    continue
                if u not in internal:
                    internal.append(u)
            internal.sort(key=lambda x: (0 if any(k in urllib.parse.urlsplit(x).path.lower() for k in NAV_KW) else 1, len(x)))
            for u in internal[:5]:
                try:
                    ext = _external_hrefs(_fetch_page(u), u)
                    scanned_norm.add(urllib.parse.urlsplit(u).path.lower().rstrip("/"))
                    pages_scanned.append(u)
                    outlinks_raw = list(dict.fromkeys(outlinks_raw + ext))
                except Exception:
                    continue

    # Clasificación de out-links
    open_data_kw = ("zenodo.org", "github.com", "figshare.com", "dryad.org", "osf.io", "dataverse", "kaggle.com", "mendeley.com/datasets", "huggingface.co", "gitlab.com")
    pid_kw = ("doi.org", "orcid.org", "crossref.org", "ncbi.nlm.nih.gov", "arxiv.org", "issn.org")
    academic_kw = (".edu", ".ac.uk", ".csic.es", "scholar.google", "dialnet", "redalyc.org", "scielo.org", "latindex.org", ".gob.", ".gov.", "inifap.gob.mx", "conacyt", "anid.cl", "minciencias", "unam.mx", "cinvestav.mx",
                   "scilit.net", "dimensions.ai", "eprints.rclis.org", "erihplus", "dulcinea", "rebiun", "doaj.org")
    media_kw = ("theconversation.com", "youtube.com", "twitter.com", "x.com", "linkedin.com", "facebook.com", "substack.com", "hypotheses.org", "instagram.com", "bsky.app")

    open_data_links = list(dict.fromkeys([l for l in outlinks_raw if any(k in l.lower() for k in open_data_kw)]))
    pid_links = list(dict.fromkeys([l for l in outlinks_raw if any(k in l.lower() for k in pid_kw)]))
    academic_links = list(dict.fromkeys([l for l in outlinks_raw if any(k in l.lower() for k in academic_kw)]))
    media_links = list(dict.fromkeys([l for l in outlinks_raw if any(k in l.lower() for k in media_kw)]))

    classified_set = set(open_data_links + pid_links + academic_links + media_links)
    other_links = [l for l in outlinks_raw if l not in classified_set]
    total_ext = len(outlinks_raw)
    total_classified = len(classified_set)

    # ---------------- 3. SERIE HISTÓRICA DE RANGOS (SOLO datos reales multi-release)
    # Cero interpolación: si no hay releases históricos indexados, la trayectoria es vacía
    # y se informa el estado con la instrucción para poblarla.
    h_data = harmonic_data or {}
    h_rank = h_data.get("harmonic_rank")
    pr_rank = h_data.get("pagerank_rank")

    trajectory = get_cc_history_trajectory(clean_dom) if (clean_dom and clean_dom != "n/d") else []
    trajectory_status = {
        "available": bool(trajectory),
        "detail": f"{len(trajectory)} release(s) real(es) indexados en CC_HISTORY_DIR."
        if trajectory
        else "Sin releases históricos indexados.",
        "action": None
        if trajectory
        else "Ejecute `python tools/cc_history.py --all` para indexar los releases 2023-2026 y activar la serie histórica real.",
    }

    # ---------------- 4. DIAGNÓSTICO DE SALUD HIPERTEXTUAL (calibrado, profesional y verificable)
    # Scoring proporcional: cada señal suma en función de su presencia REAL, sin inflar con
    # un único enlace. La etiqueta y el resumen reflejan las señales medidas, no aspiraciones.
    score = 30  # presencia base: el dominio existe y es rastreable
    if open_data_links:
        score += min(20, 5 * len(open_data_links[:4]))
    if pid_links:
        score += min(15, 3 * len(pid_links[:5]))
    if wiki_articles:
        score += min(15, 5 * len(wiki_articles[:3]))
    if academic_links:
        score += min(10, 2 * len(academic_links[:5]))
    if blog_mentions:
        score += min(15, 5 * len(blog_mentions))
    if h_rank and h_rank <= 100_000:
        score += 10
    elif h_rank and h_rank <= 2_000_000:
        score += 5
    score = min(score, 100)

    # Señales efectivamente medidas (para redactar el resumen con datos, no con adjetivos).
    señal_bits = []
    if wiki_articles:
        señal_bits.append(f"{_n_es(len(wiki_articles), 'cita en Wikipedia', 'citas en Wikipedia')}")
    if blog_mentions:
        n_posts = len(blog_mentions[0].get('posts', []))
        posts_txt = f" ({n_posts} notas)" if n_posts else ""
        señal_bits.append(f"canal de divulgación en {blog_mentions[0].get('platform', 'Substack')}{posts_txt}")
    if open_data_links:
        señal_bits.append(f"{_n_es(len(open_data_links), 'enlace a datos abiertos', 'enlaces a datos abiertos')}")
    if pid_links:
        señal_bits.append(f"{_n_es(len(pid_links), 'enlace a DOI/ORCID', 'enlaces a DOI/ORCID')}")
    if academic_links:
        señal_bits.append(f"{_n_es(len(academic_links), 'enlace a instituciones/repositorios', 'enlaces a instituciones/repositorios')}")
    if h_rank:
        señal_bits.append(f"conectividad estructural #{h_rank:,} en el Web Graph")
    señales_txt = ", ".join(señal_bits) if señal_bits else "sin señales hipertextuales externas detectadas en la portada"

    if score >= 70:
        health_level = "Alta Presencia en Ciencia Abierta"
        health_color = "var(--brand-teal)"
        nivel_txt = "consolidada"
        evidencia_txt = "La evidencia no muestra deficiencias estructurales relevantes en las señales examinadas."
    elif score >= 50:
        health_level = "Presencia Científica Abierta Activa"
        health_color = "var(--brand-teal)"
        nivel_txt = "activa"
        evidencia_txt = "La evidencia es suficiente para considerarla funcional, pero no para calificarla de destacada."
    elif score >= 30:
        health_level = "Presencia Hipertextual Parcial"
        health_color = "var(--accent-amber, #D97706)"
        nivel_txt = "parcial"
        evidencia_txt = "La evidencia indica que la conectividad externa es insuficiente para sostener una visibilidad significativa."
    else:
        health_level = "Presencia Hipertextual Mínima"
        health_color = "#E11D48"
        nivel_txt = "mínima"
        evidencia_txt = "No existe evidencia de visibilidad externa relevante."

    # Nombre para mostrar de la publicación: título real si está disponible; si la consulta fue
    # por URL, se usa el alcance del portal (nunca se inventa el nombre oficial de la revista).
    if journal_title and "." not in journal_title:
        publicacion_ref = journal_title
    elif journal_segment:
        publicacion_ref = f"la revista del alcance '{journal_segment}'"
    else:
        publicacion_ref = "la revista"

    # Diagnóstico: primero la aclaración de la unidad medida (portal/institucional), luego las señales.
    if journal_segment or host_shared_evidence:
        opening = (
            f"Cabe aclarar que las señales corresponden al portal compartido ({clean_dom}), no a la revista en particular. "
            f"La posición de {publicacion_ref} en el Web Graph no puede separarse de la del dominio institucional. "
            f"En ese sentido, la unidad medida registra una presencia hipertextual {nivel_txt}: {señales_txt}. {evidencia_txt}"
        )
    else:
        opening = (
            f"La posición de {publicacion_ref} en el Web Graph corresponde a su propio dominio. "
            f"La unidad medida registra una presencia hipertextual {nivel_txt}: {señales_txt}. {evidencia_txt}"
        )
    ecosistema_txt = ""
    if host_ecosystem["shared"] and host_ecosystem["other_journals_citations"] > 0:
        otras_rev = ", ".join(host_ecosystem["other_journals"][:4]) if host_ecosystem["other_journals"] else "otras revistas"
        ecosistema_txt = (
            f" De las {host_ecosystem['host_total_wikipedia_citations']} citas del host en Wikipedia, "
            f"{_otras_citas_frase(host_ecosystem['other_journals_citations'], host_ecosystem['host_total_wikipedia_citations'])} "
            f"({otras_rev}); la conectividad estructural del dominio es colectiva."
        )

    # Veredicto, sin matices motivacionales.
    conclusion = f"Veredicto: {evidencia_txt}"
    if journal_segment or host_shared_evidence:
        conclusion += (
            f" La posición de la revista en el Web Graph no puede separarse de la del dominio institucional; "
            f"su aporte propio se limita a {_n_es(host_ecosystem['journal_wikipedia_citations'], 'cita en Wikipedia', 'citas en Wikipedia')}."
        )

    health_summary = opening + ecosistema_txt

    # Recomendaciones específicas, con datos reales (no frases genéricas).
    recommendations = []
    if not open_data_links:
        recommendations.append(
            "Para lograr esa visibilidad, es pertinente que la revista adopte una política editorial que exija que cada "
            "artículo declare, de forma clara y pública, dónde están disponibles sus datos y los códigos utilizados, con "
            "enlaces directos a repositorios abiertos como Zenodo, Figshare, GitHub u OSF. Actualmente no se detectaron "
            "enlaces a repositorios de datos abiertos en la portada."
        )
    else:
        n_open = len(open_data_links)
        verb = "Se detectó" if n_open == 1 else "Se detectaron"
        sust = "enlace" if n_open == 1 else "enlaces"
        recommendations.append(
            f"{verb} {n_open} {sust} a repositorios de datos abiertos (p. ej. {open_data_links[0]}). Mantener la práctica "
            f"ampliándola a los datos y códigos de cada artículo."
        )

    if not pid_links:
        recommendations.append(
            "Tampoco se detectaron enlaces a identificadores persistentes (DOI/ORCID) en la portada. Asegurar que el "
            "gestor OJS resuelva cada referencia bibliográfica como hipervínculo activo (https://doi.org/...) y que los "
            "perfiles de autor expongan ORCID."
        )
    else:
        n_pid = len(pid_links)
        verb = "Se detectó" if n_pid == 1 else "Se detectaron"
        sust = "enlace" if n_pid == 1 else "enlaces"
        recommendations.append(
            f"{verb} {n_pid} {sust} a identificadores persistentes (p. ej. {pid_links[0]}). "
            f"Verificar que todas las referencias bibliográficas y los perfiles de autor se resuelvan como enlaces activos."
        )

    if not wiki_articles:
        recommendations.append(
            "Sin citas detectadas en Wikipedia para el alcance auditado. Elaborar productos de divulgación —blog, "
            "publicaciones en redes sociales, podcast o formatos transmedia— que enuncien el DOI de cada artículo y "
            "mencionen a la revista, para invitar a citarla."
        )
    else:
        n_wiki = len(wiki_articles)
        verb = "Se registró" if n_wiki == 1 else "Se registraron"
        rec = (
            f"{verb} {_n_es(n_wiki, 'cita en Wikipedia', 'citas en Wikipedia')}. Proteger esta presencia: revisar que "
            f"los enlaces citados sigan activos y elaborar productos de divulgación que inviten a citar los artículos: "
            f"blog, publicaciones en redes sociales, podcast o productos transmedia que enuncien el DOI del artículo y "
            f"mencionen a la revista."
        )
        if journal_segment:
            rec += " Al ser un portal compartido, conviene confirmar que esas citas corresponden a esta revista y no a otras del host."
        recommendations.append(rec)

    if blog_mentions and not any("substack" in l.lower() for l in outlinks_raw):
        first_b = blog_mentions[0]
        recommendations.append(
            f"Desconexión editorial detectada: La revista cuenta con un canal activo de divulgación en {first_b.get('platform', 'Substack')} "
            f"('{first_b.get('source', '')}' en {first_b.get('url', '')}), pero su portal oficial OJS no incluye ningún enlace saliente hacia él. "
            f"Es prioritario añadir un enlace directo al Substack en la cabecera, barra lateral o pie de página del portal OJS para capitalizar lectores y tracción bidireccional."
        )

    li_mentions = [b for b in blog_mentions if b.get("platform") == "LinkedIn"]
    if li_mentions and not any("linkedin" in l.lower() for l in outlinks_raw):
        first_li = li_mentions[0]
        recommendations.append(
            f"Desconexión en redes profesionales: La revista dispone de página oficial en LinkedIn ('{first_li.get('source', '')}' en {first_li.get('url', '')}), "
            f"pero su portal OJS no incluye ningún enlace saliente hacia ella. Se recomienda vincular la página de LinkedIn en la cabecera o barra lateral de OJS para potenciar la difusión e impacto profesional de los artículos."
        )

    recommendations.append(
        "También es importante revisar las directivas de robots.txt del portal para garantizar acceso transparente de "
        "rastreadores de acceso abierto (CCBot) y que el índice OAI-PMH sea descubrible e indexable."
    )

    if host_ecosystem["shared"] and host_ecosystem["other_journals_citations"] > 0:
        otras_rev = ", ".join(host_ecosystem["other_journals"][:4]) if host_ecosystem["other_journals"] else "otras revistas del portal"
        recommendations.append(
            f"Nota de ecosistema: {_otras_citas_frase(host_ecosystem['other_journals_citations'], host_ecosystem['host_total_wikipedia_citations'])} "
            f"({otras_rev}). La revista comparte la visibilidad del portal; coordinar la marca, los enlaces cruzados "
            f"entre sus revistas y un OAI-PMH unificado multiplica el alcance de todas las publicaciones del host."
        )

    # ---------------- 5. CTA DE CONSULTORÍA TINKUY LAB
    cta = {
        "title": "Tinkuy Lab puede ayudar a su revista a superar estos puntos",
        "subtitle": "Acompañamiento editorial para revistas científicas",
        "description": (
            f"En Tinkuy Lab acompañamos a las revistas en cada uno de los puntos señalados: apertura de datos, "
            f"identificadores persistentes (DOI/ORCID), divulgación transmedia e indexabilidad para agentes de IA. "
            f"Contáctenos para una valoración editorial de {publicacion_ref}."
        ),
        "button_text": "Contactar a Tinkuy Lab",
        "email_target": "culturacientifica@thinkuy.org",
        "email_subject": f"Acompañamiento editorial Tinkuy Lab: {publicacion_ref}",
        "email_body": (
            f"Hola, equipo de Tinkuy Lab:\n\n"
            f"He revisado el diagnóstico de visibilidad web de {publicacion_ref} (Dominio: {domain or 'N/D'}).\n\n"
            f"Nos interesaría recibir una valoración editorial sobre apertura de datos, identificadores persistentes, "
            f"divulgación transmedia e indexabilidad para agentes de IA.\n\n"
            f"Saludos cordiales,"
        )
    }

    oa = openalex_meta or {}

    # ---- Rúbrica SCIVIS (documentada, determinista, nunca simula)
    rubric = {
        "name": "SCIVIS Connectivity Health Index v2",
        "base": 30,
        "weights": {
            "open_data_outlinks": "5 por enlace (máx 20)",
            "persistent_id_outlinks": "3 por enlace (máx 15)",
            "wikipedia_inlinks": "5 por cita (máx 15)",
            "academic_institutional_outlinks": "2 por enlace (máx 10)",
            "cc_connectivity": "10 si HC ≤ 100k; 5 si HC ≤ 2M",
        },
        "max": 100,
        "note": "Índice heurístico de salud hipertextual: suma determinista de señales reales medidas "
                "en la portada (enlaces) y el grafo (conectividad). Es orientativo y de presentación "
                "profesional; la métrica de posicionamiento principal sigue siendo la Centralidad "
                "Armónica oficial de Common Crawl.",
    }

    wikipedia_sample = [
        {"lang": a.get("lang"), "title": a.get("title"), "url": a.get("wiki_url") or a.get("target_url") or "",
         "matched_url": a.get("target_url") or ""}
        for a in wiki_articles[:8]
    ]
    out_categories = [
        {"key": "open_data", "count": len(open_data_links), "label": "Datos y Código Abierto", "icon": "database", "sample": open_data_links[0] if open_data_links else ""},
        {"key": "persistent_ids", "count": len(pid_links), "label": "Identificadores Persistentes (DOI / ORCID)", "icon": "fingerprint", "sample": pid_links[0] if pid_links else ""},
        {"key": "academic_institutional", "count": len(academic_links), "label": "Instituciones y Repositorios", "icon": "account_balance", "sample": academic_links[0] if academic_links else ""},
        {"key": "media_social", "count": len(media_links), "label": "Prensa, Blogs y Canales de Difusión", "icon": "share", "sample": media_links[0] if media_links else ""},
    ]
    if other_links:
        out_categories.append({
            "key": "other_links",
            "count": len(other_links),
            "label": "Red Editorial, Aliados y Otros Enlaces Web",
            "icon": "hub",
            "sample": other_links[0] if other_links else "",
        })
    referrers = get_real_referrers(clean_dom)
    web_twins = compute_web_twins(clean_dom, pr_rank)

    return {
        "domain": clean_dom,
        "journal_title": journal_title,
        "host_is_shared": host_shared_evidence,
        "host_ecosystem": host_ecosystem,
        "in_links": {
            "wikipedia_count": len(wiki_articles),
            "wikipedia_note": wiki_note,
            "wikipedia_sample": wikipedia_sample,
            "blogs": {"count": len(blog_mentions), "mentions": blog_mentions[:5]},
            "openalex_citations": {
                "total_cited_by": oa.get("global_cites"),
                "works_count": oa.get("global_works"),
            },
            "common_crawl": {
                "harmonic_rank": h_rank,
                "pagerank_rank": pr_rank,
                "n_hosts": h_data.get("n_hosts"),
                "release": h_data.get("release") or CC_RELEASE_ID,
            },
            "referrers": referrers,
            "web_twins": web_twins,
        },
        "out_links": {
            "scanned_url": scanned_url,
            "pages_scanned": pages_scanned,
            "total_external": total_ext,
            "total_extracted": total_ext,
            "total_classified": total_classified,
            "all_links": outlinks_raw,
            "other_links": other_links,
            "note": "Portada resuelta + hasta 5 páginas informativas del menú de la revista (crawl 1-hop).",
            "categories": {
                c["key"]: {"count": c["count"], "label": c["label"], "icon": c["icon"], "sample": c["sample"]}
                for c in out_categories
            },
        },
        "historical_trajectory": trajectory,
        "trajectory_status": trajectory_status,
        "proximity_radar": build_web_proximity_radar(h_data, journal_title, clean_dom),
        "connectivity_health": {
            "score": score,
            "level": health_level,
            "color": health_color,
            "summary": health_summary,
            "conclusion": conclusion,
            "recommendations": recommendations,
            "rubric": rubric,
        },
        "health_badge": health_level,
        "health_summary": health_summary,
        "recommendations": recommendations,
        "consultancy_cta": cta,
    }

