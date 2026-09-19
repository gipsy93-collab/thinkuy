"""Radar de Proximidad Autoral: quién orbita tu pregunta y quién conversa con quién.

Centro configurable: una pregunta/tema libre o un artículo concreto (por DOI).
Radio = proximidad ponderada (determinista y explicable):
    proximity = w1·afinidad_temática + w2·conexión_citacional + w3·actualidad + w4·productividad
Ángulo = sector temático dominante (partición del campo).
Tamaño del nodo = centralidad (degree/betweenness/hub).
Aristas = coautoría + citación + revista compartida (red multiplex, como Pajek).
"""
from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from datetime import date

# Configurable parameters (default values)
AFFINITY_DIVISOR = 60  # divisor for thematic affinity scaling
PRODUCTIVITY_CONSTANT = 5.0  # constant in productivity formula n/(n+C)
MIN_DIST = 11.0  # minimum distance between nodes in force layout
JITTER_LEVELS = [-6.0, 3.0, -3.0, 6.0, 0.0]  # deterministic radial jitter pattern
RECENCY_DECAY = "linear"  # "linear" or "exponential"
NORMALIZE_MULTIPLEX_WEIGHTS = True  # whether to normalize multiplex edge weights

from . import db
from . import network as net
from . import topics as topics_mod
from .matching import FIELD_WEIGHTS, match_article, parse_keywords, rank_articles
from .normalize import norm


def _work_keyword_strings(article: dict) -> list[str]:
    """Normaliza las palabras clave declaradas de un artículo preservando su texto."""
    return topics_mod.declared_keyword_strings(article)


# Puntaje de afinidad para obras cuyo autor coincide con la búsqueda por nombre.
# Paridad con la coincidencia de un término individual en el título (peso título × 2).
NAME_HIT_SCORE = FIELD_WEIGHTS["title"] * 2


def _author_name_hit(article_authors: list | None, topic_phrases: list[str],
                     topic_tokens: list[str]) -> bool:
    """¿Menciona el nombre de algún autor el tema buscado?

    `match_article` solo mira título/keywords/resumen, así que una consulta con
    nombre de persona ('Daniel Torres Salinas') nunca haría match por esa vía.
    Esta función cubre ese hueco: exige la frase completa en el nombre o al
    menos 2 tokens del tema en el mismo autor (1 si el tema es un solo token),
    para no rescatar a cualquier 'Daniel' o 'Torres' suelto.
    """
    if not topic_phrases and not topic_tokens:
        return False
    for au in article_authors or []:
        if not isinstance(au, dict):
            continue
        full = norm(f"{au.get('given') or ''} {au.get('family') or ''}")
        if not full:
            continue
        name_toks = set(full.split())
        for ph in topic_phrases:
            if ph and ph in full:
                return True
        if topic_tokens:
            hits = sum(1 for t in topic_tokens if t in name_toks)
            if hits >= 2 or (len(topic_tokens) == 1 and hits == 1):
                return True
    return False


def _top_keywords(works: list[dict], limit: int = 8) -> list[dict]:
    """Agrega las palabras clave utilizables (declaradas o derivadas) de las obras del autor."""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for work in works or []:
        for keyword in work.get("keywords") or []:
            normalized = norm(keyword)
            if not normalized:
                continue
            display.setdefault(normalized, keyword)
            counts[normalized] = counts.get(normalized, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], display[item[0]].lower()))
    return [{"keyword": display[normalized], "n": count} for normalized, count in ranked[:limit]]


def _weights(raw: str | None) -> list[float]:
    try:
        w = [float(x) for x in (raw or "0.4,0.3,0.2,0.1").split(",")][:4]
    except ValueError:
        w = [0.4, 0.3, 0.2, 0.1]
    while len(w) < 4:
        w.append(0.0)
    s = sum(w) or 1.0
    return [x / s for x in w]


def radar(conn: sqlite3.Connection,
          topic: str | None = None,
          doi: str | None = None,
          weights: str | None = None,
          limit: int = 25,
          min_works: int = 1,
          excluded: list[str] | None = None,
          included: list[str] | None = None,
          affinity_divisor: int = AFFINITY_DIVISOR,
          productivity_constant: float = PRODUCTIVITY_CONSTANT,
          min_dist: float = MIN_DIST,
          recency_decay: str = RECENCY_DECAY,
          normalize_weights: bool = NORMALIZE_MULTIPLEX_WEIGHTS) -> dict:
    """Construye el radar. center = topic o article (por DOI). Permite excluir e incluir autores."""
    weights_list = _weights(weights)
    raw_excl = {norm(x.strip()) for x in (excluded or []) if x and x.strip()}
    raw_incl = {norm(x.strip()) for x in (included or []) if x and x.strip()}
    net_data = net.build_author_edges(conn, min_works=min_works, include_terms=raw_incl)
    authors = net_data["authors"]
    identity_map = net_data.get("identity_map", {})

    # Resolver nombres, orcids y claves de autor
    excl_set: set[str] = set()
    incl_set: set[str] = set()
    for key, info in authors.items():
        k_norm = norm(key)
        name_norm = norm(info.get("name") or "")
        orcid_val = norm(info.get("orcid") or "")
        if k_norm in raw_excl or (name_norm and name_norm in raw_excl) or (orcid_val and orcid_val in raw_excl):
            excl_set.add(key)
        if k_norm in raw_incl or (name_norm and name_norm in raw_incl) or (orcid_val and orcid_val in raw_incl):
            incl_set.add(key)
    excl_set.update(raw_excl)
    incl_set.update(raw_incl)

    # --- centro: pregunta libre o artículo
    center = {"type": "topic", "label": topic or ""}
    topic_kws: list[str] = []
    target = None
    if doi:
        target = db.get_article(conn, doi.strip().lower())
        if target:
            center = {"type": "article", "label": target.get("title"),
                      "doi": target.get("doi"), "journal": target.get("journal_title")}
            blob = " ".join(filter(None, [
                target.get("title"),
                " ".join(k if isinstance(k, str) else k.get("k", "") for k in (target.get("keywords") or [])),
                (target.get("abstract") or "")[:800],
            ]))
            topic_kws = parse_keywords(blob)
    if not topic_kws and topic:
        topic_kws = parse_keywords(topic)
        # Desplegar frase + tokens individuales: la frase conserva el bonus de
        # precisión y los tokens dan recall (p. ej. 'altmetrics Daniel Torres
        # Salinas' antes exigía los 4 términos juntos y devolvía cero).
        expanded: list[str] = []
        for kw in topic_kws:
            if kw not in expanded:
                expanded.append(kw)
            for tok in kw.split():
                if tok not in expanded:
                    expanded.append(tok)
        topic_kws = expanded

    # --- afinidad temática y conexión citacional por autor
    rows = conn.execute("SELECT * FROM articles").fetchall()
    arts = [db._row_to_article(r) for r in rows]

    ranked = rank_articles(arts, topic_kws) if topic_kws else []
    topic_ids = {a["id"] for a in ranked if a["match_score"] > 0}
    # Coincidencia por nombre de autor: match_article no mira el campo autores,
    # así que las búsquedas de personas se perderían sin este pase.
    topic_phrases = [norm(kw) for kw in topic_kws if len(kw.split()) > 1]
    topic_tokens = sorted({t for kw in topic_kws for t in norm(kw).split() if len(t) >= 3})
    name_ids: set[int] = set()
    if topic_phrases or topic_tokens:
        for a in arts:
            if _author_name_hit(a.get("authors"), topic_phrases, topic_tokens):
                name_ids.add(a["id"])
    topic_ids |= name_ids
    if target:
        target_keywords, target_keyword_source = topics_mod.display_keywords(
            target, candidate_terms=topic_kws, limit=6
        )
        center.update({
            "authors": target.get("authors"),
            "year": target.get("year"),
            "keywords": target_keywords,
            "keyword_source": target_keyword_source,
            "abstract": (target.get("abstract") or "")[:800],
        })

    # identidades de work del target (para conexión citacional por artículo)
    target_ids = net._work_identifiers(target) if target else set()
    work_to_authors: dict[str, set] = {}
    art_by_id: dict[int, dict] = {}
    for a in arts:
        art_by_id[a["id"]] = a
        for wid in net._work_identifiers(a):
            work_to_authors.setdefault(wid, set()).add(
                frozenset(net.canonical_author_id(au, identity_map) for au in (a.get("authors") or []) if isinstance(au, dict) and net.canonical_author_id(au, identity_map))
            )

    author_profile: dict[str, dict] = {}
    for a in arts:
        keys = [net.canonical_author_id(au, identity_map) for au in (a.get("authors") or []) if isinstance(au, dict)]
        keys = [k for k in keys if k and k in authors]
        if not keys:
            continue
        m = match_article(a, topic_kws)["score"] if topic_kws else 0
        if a["id"] in name_ids:
            m = max(m, NAME_HIT_SCORE)
        in_topic = a["id"] in topic_ids
        cites_target = bool(target_ids and (net._work_identifiers(a) & target_ids))
        cited_by_target = bool(target and a["id"] != target["id"] and target_ids & net._work_identifiers(a))
        for k in keys:
            p = author_profile.setdefault(k, {"max_affinity": 0, "topic_works": 0, "works": 0,
                                              "cites_target": 0, "cited_by_target": 0})
            p["works"] += 1
            p["max_affinity"] = max(p["max_affinity"], m)
            if in_topic:
                p["topic_works"] += 1
            if cites_target:
                p["cites_target"] += 1
            if cited_by_target:
                p["cited_by_target"] += 1

    # --- proximidad
    scores: list[tuple[float, str]] = []
    components_map: dict[str, dict[str, float]] = {}
    year_now = date.today().year
    years = [int((v.get("last") or "")[:4]) for v in authors.values() if v.get("last")]
    y_min, y_max = (min(years), max(years)) if years else (year_now - 2, year_now)

    for key, info in authors.items():
        if key in excl_set:
            continue
        p = author_profile.get(key)
        if not p:
            continue
        n = info["n"]
        if n < min_works and key not in incl_set:
            continue
        affinity = min(1.0, p["max_affinity"] / affinity_divisor) if topic_kws else 0.0
        if center["type"] == "article" and target:
            connection = min(1.0, (p["cites_target"] + p["cited_by_target"]) / max(1, p["works"]))
        else:
            connection = p["topic_works"] / max(1, p["works"]) if topic_ids else 0.0
        if not topic_kws and center["type"] == "topic":
            affinity = 0.0
            connection = 0.0
        last_y = int((info.get("last") or "")[:4]) if info.get("last") else y_min
        if recency_decay == "exponential":
            recency = 1 - math.exp(-(last_y - y_min) / (y_max - y_min + 1e-6))
        else:
            recency = (last_y - y_min) / max(1, y_max - y_min)
        productivity = n / (n + productivity_constant)
        prox = (weights_list[0] * affinity + weights_list[1] * connection + weights_list[2] * recency + weights_list[3] * productivity)
        if center["type"] == "topic" and not topic_kws:
            prox = weights_list[2] * recency + weights_list[3] * productivity  # sin términos: solo trayectoria
        if prox > 0 or center["type"] == "article" or key in incl_set:
            scores.append((prox, key))
        components_map[key] = {
            "affinity": round(affinity, 4),
            "connection": round(connection, 4),
            "recency": round(recency, 4),
            "productivity": round(productivity, 4),
        }
    scores.sort(key=lambda kv: -kv[0])

    # Construir lista de seleccionados dando prioridad a los incluidos explícitamente
    forced = [k for k in incl_set if k in authors and k not in excl_set]
    seen_selected = set(forced)
    selected = list(forced)
    for _p, k in scores:
        if k not in seen_selected:
            selected.append(k)
            seen_selected.add(k)
        if len(selected) >= max(limit, len(forced)):
            break

    # --- SNA sobre el subgrafo seleccionado
    sub_nodes = set(selected)
    co = {e: v for e, v in net_data["coauthor"].items() if e <= sub_nodes}
    jrn = {e: v for e, v in net_data["journal"].items() if e <= sub_nodes}
    cit = {e: v for e, v in net_data["citation"].items() if e[0] in sub_nodes and e[1] in sub_nodes}
    deg = net.degree(sub_nodes, co)
    btwn = net.betweenness(sub_nodes, co)
    hub, auth = net.hits(cit, sub_nodes)
    comm = net.communities(sub_nodes, co)
    core = net.k_cores(sub_nodes, co)

    # Recolectar lista estructurada de obras para los autores seleccionados
    author_works: dict[str, list[dict]] = defaultdict(list)
    for a in arts:
        raw_aus = [au for au in (a.get("authors") or []) if isinstance(au, dict)]
        art_authors = []
        for au in raw_aus:
            g, f = net.clean_author_name(str(au.get("given") or ""), str(au.get("family") or ""))
            art_authors.append({
                "name": f"{g} {f}".strip() or "Autor",
                "orcid": net.normalize_orcid(au.get("orcid")),
                "key": net.canonical_author_id(au, identity_map),
            })

        keys = [net.canonical_author_id(au, identity_map) for au in raw_aus]
        for k in keys:
            if k in sub_nodes:
                display_keywords, keyword_source = topics_mod.display_keywords(
                    a, candidate_terms=topic_kws, limit=6
                )
                author_works[k].append({
                    "id": a["id"],
                    "title": a["title"],
                    "year": a.get("year"),
                    "journal": a.get("journal_title"),
                    "doi": a.get("doi"),
                    "url": a.get("url") or (f"https://doi.org/{a['doi']}" if a.get("doi") else None),
                    "abstract": (a.get("abstract") or "")[:400],
                    "cited_by": a.get("cited_by") or 0,
                    "is_topic": a["id"] in topic_ids,
                    "keywords": display_keywords,
                    "keyword_source": keyword_source,
                    "authors": art_authors,
                })
    for k in author_works:
        author_works[k].sort(key=lambda w: (-int(w["is_topic"]), -(w["year"] or 0)))

    # --- posiciones polares: ángulo por sector, radio = 1 - proximidad
    sectors = sorted({authors[k]["sector"] for k in selected}) if selected else []
    n_sectors = max(1, len(sectors))
    # Cada sector ocupa un arco de 2π/n_sectors; centramos el arco en la posición base
    sector_arc = 2 * math.pi / n_sectors
    sector_base_angle = {s: sector_arc * i for i, s in enumerate(sectors)}

    prox_values = [p for p, _ in scores[:limit] if p > 0]
    min_p = min(prox_values) if prox_values else 0.0
    max_p = max(prox_values) if prox_values else 1.0
    p_range = max(0.001, max_p - min_p)

    # Contadores de autores por sector para dispersar el ángulo
    sector_counts: dict[str, int] = defaultdict(int)
    for key in selected:
        sector_counts[authors[key]["sector"]] += 1
    sector_index: dict[str, int] = defaultdict(int)

    nodes = []
    for key in selected:
        info = authors[key]
        p = next((_p for _p, k in scores if k == key), 0.0)

        # Mapeo normalizado: mayor proximidad = más cerca del centro (r entre 15% y 90% de R)
        norm_score = (p - min_p) / p_range if p_range > 0 else 0.5
        norm_score = min(1.0, max(0.0, norm_score))
        radius = (1.0 - norm_score) * 75.0 + 15.0

        # Dispersión angular: distribuir uniformemente dentro del arco del sector
        base_ang = sector_base_angle.get(info["sector"], 0.0)
        idx_in_sector = sector_index[info["sector"]]
        total_in_sec = sector_counts[info["sector"]]
        sector_index[info["sector"]] += 1

        if n_sectors == 1:
            # Caso de sector único: distribuir a lo largo de los 360 grados
            ang = base_ang + (idx_in_sector / total_in_sec) * 2 * math.pi
        elif total_in_sec > 1:
            usable_arc = sector_arc * 0.88  # 88% del arco para dejar separación visual entre sectores
            frac = idx_in_sector / (total_in_sec - 1)  # 0..1
            ang = base_ang + (frac - 0.5) * usable_arc
        else:
            ang = base_ang

        # Jitter radial multiescala: evitar radios idénticos para proximidades similares
        if total_in_sec > 1:
            radial_jitter = JITTER_LEVELS[idx_in_sector % len(JITTER_LEVELS)]
            radius = max(12.0, min(92.0, radius + radial_jitter))

        # Coautores frecuentes dentro de la red seleccionada
        top_co = []
        for pair, weight in co.items():
            pair_list = list(pair)
            if len(pair_list) == 2:
                a_id, b_id = pair_list[0], pair_list[1]
                if a_id == key and b_id in authors:
                    top_co.append({"name": authors[b_id]["name"], "key": b_id, "weight": weight, "orcid": authors[b_id].get("orcid")})
                elif b_id == key and a_id in authors:
                    top_co.append({"name": authors[a_id]["name"], "key": a_id, "weight": weight, "orcid": authors[a_id].get("orcid")})
        top_co.sort(key=lambda c: -c["weight"])

        selected_works = author_works.get(key, [])
        work_sources = {work.get("keyword_source") for work in selected_works}
        keyword_source = "declared" if "declared" in work_sources else ("derived" if "derived" in work_sources else "none")
        nodes.append({
            "id": key,
            "name": info["name"],
            "orcid": info.get("orcid"),
            "identity_status": info.get("identity_status", "unverified"),
            "n": info["n"],
            "proximity": round(p, 4),
            "components": components_map.get(key, {
                "affinity": 0.0, "connection": 0.0, "recency": 0.0, "productivity": 0.0,
            }),
            "sector": info["sector"],
            "x": round(radius * math.cos(ang), 2),
            "y": round(radius * math.sin(ang), 2),
            "degree": deg.get(key, {}).get("degree", 0),
            "betweenness": round(btwn.get(key, 0.0), 5),
            "hub": round(hub.get(key, 0.0), 5),
            "authority": round(auth.get(key, 0.0), 5),
            "community": comm.get(key, 0),
            "k_core": core.get(key, 0),
            "first_year": int((info.get("first") or "")[:4]) if info.get("first") else None,
            "last_year": int((info.get("last") or "")[:4]) if info.get("last") else None,
            "journals": sorted(info.get("journals") or [])[:5],
            "coauthors": top_co[:4],
            "top_keywords": _top_keywords(selected_works),
            "keyword_source": keyword_source,
            "works_list": selected_works,
        })

    # --- Repulsión post-layout (force-directed relaxation) determinista y amortiguada
    # distancia mínima segura entre nodos (configurable)
    for iteration in range(60):
        moved = False
        damping = max(0.15, 0.45 * (1.0 - iteration / 60))
        disp_x = [0.0] * len(nodes)
        disp_y = [0.0] * len(nodes)

        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                dx = nodes[i]["x"] - nodes[j]["x"]
                dy = nodes[i]["y"] - nodes[j]["y"]
                dist = math.hypot(dx, dy)
                if dist < min_dist and dist > 0.001:
                    force = (min_dist - dist) * damping
                    ux, uy = dx / dist, dy / dist
                    disp_x[i] += ux * force
                    disp_y[i] += uy * force
                    disp_x[j] -= ux * force
                    disp_y[j] -= uy * force
                    moved = True
                elif dist <= 0.001:
                    offset_ang = (i * 0.6180339887) * 2 * math.pi
                    disp_x[i] += math.cos(offset_ang) * min_dist * 0.5 * damping
                    disp_y[i] += math.sin(offset_ang) * min_dist * 0.5 * damping
                    moved = True

        if not moved:
            break

        for i, n in enumerate(nodes):
            n["x"] = round(n["x"] + disp_x[i], 2)
            n["y"] = round(n["y"] + disp_y[i], 2)
            # Reclamp suave dentro de límites admisibles (10 <= radio <= 94)
            d = math.hypot(n["x"], n["y"])
            if d > 94.0:
                scale = 94.0 / d
                n["x"] = round(n["x"] * scale, 2)
                n["y"] = round(n["y"] * scale, 2)
            elif d < 10.0:
                scale = 10.0 / max(d, 0.1)
                n["x"] = round(n["x"] * scale, 2)
                n["y"] = round(n["y"] * scale, 2)

    edges = []
    # Normalizar pesos de capas multiplex si se solicita
    if normalize_weights:
        max_co = max(co.values()) if co else 1
        max_jrn = max(jrn.values()) if jrn else 1
        max_cit = max(cit.values()) if cit else 1
        co = {e: v / max_co for e, v in co.items()}
        jrn = {e: v / max_jrn for e, v in jrn.items()}
        cit = {e: v / max_cit for e, v in cit.items()}
    for (a, b), v in co.items():
        if a in sub_nodes and b in sub_nodes:
            edges.append({"a": a, "b": b, "type": "coauthor", "weight": v})
    for (a, b), v in jrn.items():
        if a in sub_nodes and b in sub_nodes:
            edges.append({"a": a, "b": b, "type": "journal", "weight": v})
    for (a, b), v in cit.items():
        edges.append({"a": a, "b": b, "type": "citation", "weight": v})

    # Etiquetas legibles de los sectores (ids de campo -> nombre del perfil)
    try:
        sector_labels = {f.get("id"): f.get("name") for f in topics_mod.fields() if f.get("id")}
    except Exception:
        sector_labels = {}
    sector_labels.setdefault("general", "General / transversal")

    return {
        "center": center,
        "weights": {"w1_affinity": weights_list[0], "w2_connection": weights_list[1], "w3_recency": weights_list[2], "w4_productivity": weights_list[3]},
        "sectors": sectors,
        "sector_labels": sector_labels,
        "count": len(nodes),
        "excluded": list(excl_set),
        "included": list(incl_set),
        "resolved_included": sorted(set(forced)),
        "nodes": nodes,
        "edges": edges,
        "method": "determinista: proximidad ponderada + red multiplex (modelo Pajek)",
    }