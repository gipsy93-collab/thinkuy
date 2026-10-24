"""Grafo de citas: quién cita a quién, co-citación y hubs.

Se construye sobre los datos ya depositados: `referenced_ids` (OpenAlex IDs) y
`s2_references` (Semantic Scholar: DOIs o paperIds). Todo determinista.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections import Counter, defaultdict
from typing import Any

from .conversation import strip_oaid
from .normalize import clean_doi  # canónico en normalize; re-exportado para `cited.py`

log = logging.getLogger("radar.citation_graph")


def build_index(conn: sqlite3.Connection) -> dict:
    """Índice de identidad → article (openalex_id, doi y s2_paper_id → id)."""
    idx: dict[str, int] = {}
    for r in conn.execute("SELECT id, openalex_id, doi, source, source_id, s2_paper_id FROM articles").fetchall():
        oid = strip_oaid(r["openalex_id"] or (r["source_id"] if r["source"] == "openalex" else None))
        if oid:
            idx[oid] = r["id"]
        doi = clean_doi(r["doi"])
        if doi:
            idx.setdefault(f"doi:{doi}", r["id"])
        spid = (r["s2_paper_id"] or "").strip().upper()
        if spid:
            idx.setdefault(f"s2:{spid}", r["id"])
    return idx


def _ref_keys(refs: list) -> set[str]:
    out: set[str] = set()
    for x in refs or []:
        if not x:
            continue
        s = str(x).strip()
        if s.lower().startswith("doi:"):
            out.add(s.lower())
        elif s.lower().startswith("http") or s.startswith("W"):
            out.add(strip_oaid(s))
        elif re.fullmatch(r"[0-9a-fA-F]{40}", s) or s.isdigit():
            # paperId / CorpusID de Semantic Scholar (sin DOI): clave propia
            out.add(f"s2:{s.upper()}")
        else:
            # DOI crudo
            out.add(f"doi:{s.lower()}")
    return out


def resolve_article_ids(conn: sqlite3.Connection, dois: list[str] | None) -> set[int]:
    """Resuelve DOIs (o IDs OpenAlex) a ids internos del catálogo."""
    if not dois:
        return set()
    idx = build_index(conn)
    out: set[int] = set()
    flat_dois: list[str] = []
    for d in dois:
        if not d:
            continue
        for part in str(d).split(","):
            part_s = part.strip()
            if part_s:
                flat_dois.append(part_s)

    for s in flat_dois:
        c_doi = clean_doi(s)
        aid = idx.get(f"doi:{c_doi}") or idx.get(strip_oaid(s))
        if not aid and c_doi:
            row = conn.execute(
                "SELECT id FROM articles WHERE LOWER(doi) = ? OR doi LIKE ? LIMIT 1",
                (c_doi, f"%{c_doi}%"),
            ).fetchone()
            if row:
                aid = row["id"]
        if aid:
            out.add(aid)
    return out


def build_edges(conn: sqlite3.Connection, citer_ids: set[int] | None = None) -> list[tuple[int, int]]:
    """Aristas de citación (citer_id, cited_id) dentro del catálogo.

    Con `citer_ids`, solo se consideran las citas salientes de ese corpus
    (p. ej. los resultados de una consulta); el citado puede estar fuera del
    corpus (fundamentos). Sin filtro, grafo global del catálogo.
    """
    idx = build_index(conn)
    edges: list[tuple[int, int]] = []
    if citer_ids is not None:
        if not citer_ids:
            return []
        placeholders = ",".join(["?"] * len(citer_ids))
        rows = conn.execute(
            f"SELECT id, referenced_ids, s2_references FROM articles WHERE id IN ({placeholders})",
            list(citer_ids),
        ).fetchall()
    else:
        rows = conn.execute("SELECT id, referenced_ids, s2_references FROM articles").fetchall()
    for r in rows:
        citer = r["id"]
        keys = set()
        for col in ("referenced_ids", "s2_references"):
            try:
                keys |= _ref_keys(json.loads(r[col] or "[]"))
            except (json.JSONDecodeError, TypeError):
                continue
        for k in keys:
            cited = idx.get(k)
            if cited and cited != citer:
                edges.append((citer, cited))
    return edges


def build_live_graph(dois: list[str], *, refs_por_obra: int = 15, max_obras: int = 400,
                     http=None) -> sqlite3.Connection:
    """Construye un grafo de citas **en vivo** (OpenAlex) sobre los DOIs dados.

    Motivo: el catálogo solo trae referencias del **15%** de sus artículos, así que SPC y
    co-citación se calculaban sobre un grafo flaco (434 nodos, densidad 0,004). Aquí se piden a
    OpenAlex las obras del corpus **y sus referencias**, y se arma el grafo en una base **temporal
    en memoria** —sin persistir nada en el catálogo del investigador—. Las funciones de grafo
    existentes operan luego sobre esa conexión tal cual.
    """
    from . import config, db
    from .harvester import openalex

    cliente = http
    cierra = False
    if cliente is None:
        import httpx

        cliente = httpx.Client(headers={"User-Agent": config.USER_AGENT},
                               follow_redirects=True, timeout=25.0)
        cierra = True

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    try:
        corpus = openalex.get_works_by_dois(cliente, dois)
        ids_refs: list[str] = []
        vistos: set[str] = set()
        for item in corpus:
            art = openalex.parse_item(item)
            if not art:
                continue
            db.upsert_article(conn, art.db_row())
            for x in (item.get("referenced_works") or [])[:refs_por_obra]:
                rk = str(x or "").replace("https://openalex.org/", "").strip()
                if rk and rk not in vistos:
                    vistos.add(rk)
                    ids_refs.append(rk)
        faltan = max(0, max_obras - len(corpus))
        for item in openalex.get_works_by_ids(cliente, ids_refs[:faltan]):
            art = openalex.parse_item(item)
            if art:
                db.upsert_article(conn, art.db_row())
    finally:
        if cierra:
            cliente.close()
    return conn


def citation_stats(conn: sqlite3.Connection) -> dict:
    """Estadísticas del grafo: nodos, aristas, densidad, mayor grado."""
    edges = build_edges(conn)
    indeg: dict[int, int] = {}
    outdeg: dict[int, int] = {}
    for a, b in edges:
        outdeg[a] = outdeg.get(a, 0) + 1
        indeg[b] = indeg.get(b, 0) + 1
    nodes = set(indeg) | set(outdeg)
    n = max(len(nodes), 1)
    density = len(edges) / (n * (n - 1)) if n > 1 else 0
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "density": round(density, 5),
        "top_indegree": sorted(indeg.items(), key=lambda kv: -kv[1])[:10],
        "top_outdegree": sorted(outdeg.items(), key=lambda kv: -kv[1])[:10],
    }


def co_cited_live(doi: str, limit: int = 10, client: Any = None) -> list[dict]:
    """Recupera artículos co-citados y relacionados directamente desde OpenAlex en tiempo real.

    Emula la experiencia para usuarios que no tienen un catálogo local precargado,
    aprovechando el cluster global de co-citación de OpenAlex ('related_works').
    """
    import httpx

    from . import config

    c_doi = clean_doi(doi)
    if not c_doi:
        return []

    close_client = False
    if client is None:
        client = httpx.Client(timeout=15.0)
        close_client = True

    try:
        url = f"https://api.openalex.org/works/https://doi.org/{c_doi}"
        resp = client.get(url, params={"mailto": config.MAILTO}, headers=config.openalex_headers())
        if resp.status_code != 200:
            return []
        data = resp.json()
        related_urls = data.get("related_works") or []
        if not related_urls:
            return []

        # Extraer IDs de obras relacionadas (W...)
        ids = [strip_oaid(u) for u in related_urls[:max(limit, 10)] if u]
        if not ids:
            return []

        filter_val = "|".join(ids[:min(len(ids), 25)])
        search_url = "https://api.openalex.org/works"
        search_resp = client.get(
            search_url,
            params={"filter": f"openalex_id:{filter_val}", "per-page": limit, "mailto": config.MAILTO},
            headers=config.openalex_headers(),
        )
        if search_resp.status_code != 200:
            return []

        results = search_resp.json().get("results") or []
        out = []
        for it in results[:limit]:
            src = (it.get("primary_location") or {}).get("source") or {}
            out.append({
                "id": None,
                "title": it.get("title") or it.get("display_name"),
                "doi": clean_doi(it.get("doi")),
                "year": it.get("publication_year"),
                "journal_title": src.get("display_name"),
                "cited_by": it.get("cited_by_count", 0),
                "shared_refs": 1,
                "source": "openalex_live",
            })
        return out
    except Exception as e:
        log.warning(f"Error consultando co-citación en vivo en OpenAlex para {doi}: {e}")
        return []
    finally:
        if close_client:
            client.close()


def co_cited(conn: sqlite3.Connection, doi: str, limit: int = 10, mode: str = "auto") -> list[dict]:
    """Papers que co-citan las mismas referencias que el DOI dado (catálogo local con fallback en vivo)."""
    if mode == "live":
        return co_cited_live(doi, limit=limit)

    idx = build_index(conn)
    target_id = idx.get(f"doi:{doi.strip().lower()}") or idx.get(strip_oaid(doi))
    if not target_id:
        if mode == "auto":
            return co_cited_live(doi, limit=limit)
        return []
    row = conn.execute("SELECT referenced_ids, s2_references FROM articles WHERE id = ?", (target_id,)).fetchone()
    if not row:
        if mode == "auto":
            return co_cited_live(doi, limit=limit)
        return []
    keys = set()
    for col in ("referenced_ids", "s2_references"):
        try:
            keys |= _ref_keys(json.loads(row[col] or "[]"))
        except (json.JSONDecodeError, TypeError):
            continue
    if not keys:
        if mode == "auto":
            return co_cited_live(doi, limit=limit)
        return []
    scored: dict[int, int] = {}
    for r in conn.execute("SELECT id, referenced_ids, s2_references FROM articles WHERE id != ?", (target_id,)).fetchall():
        try:
            rk = set()
            for col in ("referenced_ids", "s2_references"):
                rk |= _ref_keys(json.loads(r[col] or "[]"))
        except (json.JSONDecodeError, TypeError):
            continue
        inter = rk & keys
        if inter:
            scored[r["id"]] = len(inter)
    top = sorted(scored.items(), key=lambda kv: -kv[1])[:limit]
    out = []
    for aid, n in top:
        a = dict(conn.execute("SELECT id, title, doi, year, journal_title FROM articles WHERE id = ?", (aid,)).fetchone())
        out.append({**a, "shared_refs": n, "source": "local_catalog"})

    # Si hay muy pocos resultados locales y el modo es auto, complementar con en vivo
    if len(out) < 2 and mode == "auto":
        live_res = co_cited_live(doi, limit=limit)
        if live_res:
            return live_res

    return out


def hubs(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Hubs: los artículos más citados dentro del catálogo (grado de entrada)."""
    edges = build_edges(conn)
    indeg: dict[int, int] = {}
    for _a, b in edges:
        indeg[b] = indeg.get(b, 0) + 1
    top = sorted(indeg.items(), key=lambda kv: -kv[1])[:limit]
    out = []
    for aid, n in top:
        r = conn.execute("SELECT id, title, doi, year, journal_title, cited_by FROM articles WHERE id = ?", (aid,)).fetchone()
        if r:
            out.append({**dict(r), "indegree_catalog": n})
    return out


# ==============================================================================
# FASE 1: EXTENSIÓN EPISTEMOLÓGICA Y ANÁLISIS ESTRUCTURAL DE REDES DE CITACIÓN
# ==============================================================================

class UnionFind:
    """Estructura Disjoint-Set con compresión de caminos y unión por rango."""
    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def find(self, i: str) -> str:
        if i not in self.parent:
            self.parent[i] = i
            self.rank[i] = 0
            return i
        if self.parent[i] != i:
            self.parent[i] = self.find(self.parent[i])
        return self.parent[i]

    def union(self, i: str, j: str) -> None:
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i == root_j:
            return
        if self.rank[root_i] < self.rank[root_j]:
            self.parent[root_i] = root_j
        elif self.rank[root_i] > self.rank[root_j]:
            self.parent[root_j] = root_i
        else:
            self.parent[root_j] = root_i
            self.rank[root_i] += 1


def detect_cocitation_clusters(
    conn: sqlite3.Connection,
    threshold: int = 2,
    min_size: int = 2,
    max_clusters: int = 15,
    article_ids: set[int] | None = None,
    min_catalog: int = 1,
) -> list[dict]:
    """Detecta 'Escuelas de Pensamiento' mediante clustering Union-Find sobre pares de co-citación.

    Dos obras o referencias fuertemente co-citadas (frecuencia >= threshold) pertenecen
    al mismo linaje o comunidad epistemológica. Mapea las referencias hacia artículos del catálogo
    cuando están presentes.

    Con `article_ids`, los pares se acumulan solo desde ese corpus (p. ej. los
    resultados de una consulta) en vez del catálogo global.

    `min_catalog` descarta los grupos con menos de N artículos **en el catálogo**. Motivo medido
    (22-09-2026): con el umbral por defecto salían 15 «escuelas», casi todas de 6-25 referencias
    con **un solo** artículo en catálogo — ruido con forma de hallazgo.
    """
    idx = build_index(conn)
    # Invertir índice: article_id -> primary doi
    id_to_doi: dict[int, str] = {}
    for k, aid in idx.items():
        if k.startswith("doi:"):
            id_to_doi.setdefault(aid, k[4:])

    # 1. Acumular pares de referencias co-citadas
    cocit_counts: Counter = Counter()
    ref_frequency: Counter = Counter()
    article_keys: dict[int, set[str]] = {}

    if article_ids is not None:
        if not article_ids:
            article_ids = None
        else:
            placeholders = ",".join(["?"] * len(article_ids))
            rows = conn.execute(
                f"SELECT id, referenced_ids, s2_references FROM articles WHERE id IN ({placeholders})",
                list(article_ids),
            ).fetchall()
    if article_ids is None:
        rows = conn.execute("SELECT id, referenced_ids, s2_references FROM articles").fetchall()
    for r in rows:
        keys = []
        for col in ("referenced_ids", "s2_references"):
            try:
                keys.extend(_ref_keys(json.loads(r[col] or "[]")))
            except (json.JSONDecodeError, TypeError):
                continue
        # Deduplicar manteniendo orden
        uniq_keys = sorted(list(set(keys)))
        if article_ids is not None:
            article_keys[r["id"]] = set(uniq_keys)
        for k in uniq_keys:
            ref_frequency[k] += 1

        # Generar pares no dirigidos
        n = len(uniq_keys)
        for i in range(n):
            for j in range(i + 1, n):
                pair = (uniq_keys[i], uniq_keys[j])
                cocit_counts[pair] += 1

    # 2. Filtrar por umbral y unir componentes
    uf = UnionFind()
    active_pairs = [pair for pair, w in cocit_counts.items() if w >= threshold]

    # Si con el umbral dado o el subconjunto específico no hay pares, hacer fallback suave
    if not active_pairs and article_ids is not None:
        return detect_cocitation_clusters(conn, threshold=1, min_size=min_size,
                                          max_clusters=max_clusters, article_ids=None,
                                          min_catalog=min_catalog)

    for a, b in active_pairs:
        uf.union(a, b)

    clusters_map: dict[str, list[str]] = defaultdict(list)
    for a, b in active_pairs:
        root = uf.find(a)
        # Asegurar inclusión única
        clusters_map[root].append(a)
        clusters_map[root].append(b)

    # 3. Formatear y enriquecer clusters
    enriched_clusters: list[dict] = []
    seen_roots: set[str] = set()

    for root, nodes in clusters_map.items():
        if root in seen_roots:
            continue
        seen_roots.add(root)
        uniq_nodes = sorted(list(set(nodes)))
        if len(uniq_nodes) < min_size:
            continue

        # Identificar artículos del catálogo correspondientes a estos nodos
        catalog_articles = []
        canonical_refs = []
        seen_aids: set[int] = set()
        seen_titles: set[str] = set()

        for node in uniq_nodes:
            aid = idx.get(node)
            if aid:
                if aid in seen_aids:
                    continue
                seen_aids.add(aid)
                row = conn.execute(
                    "SELECT id, title, doi, year, journal_title, cited_by, keywords FROM articles WHERE id = ?",
                    (aid,),
                ).fetchone()
                if row:
                    art = dict(row)
                    title_norm = (art.get("title") or "").strip().lower()
                    if title_norm and title_norm in seen_titles:
                        continue
                    if title_norm:
                        seen_titles.add(title_norm)
                    art["role"] = classify_epistemic_role(art)
                    catalog_articles.append(art)
            else:
                canonical_refs.append({"ref_key": node, "citations": ref_frequency[node]})

        canonical_refs.sort(key=lambda x: -x["citations"])
        catalog_articles.sort(key=lambda x: -(x.get("cited_by") or 0))

        # Descarta micro-grupos sin presencia real en el catálogo (ruido con forma de «escuela»)
        if len(catalog_articles) < min_catalog:
            continue

        # Extraer keywords dominantes para etiquetar la escuela
        kw_counter: Counter = Counter()
        for ca in catalog_articles:
            try:
                kws = json.loads(ca.get("keywords") or "[]") if isinstance(ca.get("keywords"), str) else ca.get("keywords", [])
                for kw in kws:
                    kw_counter[str(kw).strip().lower()] += 1
            except Exception:
                pass
        dominant_topics = [k for k, _ in kw_counter.most_common(5) if len(k) > 3]

        # Anclaje en el corpus consultado: cuántas obras de la consulta
        # conversan con esta escuela (citan ≥1 de sus referencias). Escuelas
        # ancladas primero, fundamentos externos después.
        node_set = set(uniq_nodes)
        if article_ids is not None:
            corpus_count = sum(1 for keys in article_keys.values() if keys & node_set)
        else:
            corpus_count = 0

        enriched_clusters.append({
            "cluster_id": len(enriched_clusters) + 1,
            "total_nodes": len(uniq_nodes),
            "catalog_count": len(catalog_articles),
            "corpus_count": corpus_count,
            "dominant_topics": dominant_topics,
            "representative_articles": catalog_articles[:6],
            "canonical_references": canonical_refs[:6],
        })

    # Ordenar: ancladas en el corpus, luego con presencia en catálogo, luego tamaño
    enriched_clusters.sort(key=lambda c: (-c["corpus_count"], -c["catalog_count"], -c["total_nodes"]))
    return enriched_clusters[:max_clusters]


def calculate_main_path(
    conn: sqlite3.Connection,
    top_n: int = 20,
    article_ids: set[int] | None = None,
) -> list[dict]:
    """Calcula la Trayectoria Principal (Main Path Analysis) de citación en el catálogo.

    Implementa una versión determinista de Search Path Count (SPC) sobre el DAG
    de citas internas: identifica la 'autopista' histórica del conocimiento que
    conecta los fundamentos tempranos con las publicaciones contemporáneas.

    Con `article_ids`, el SPC se calcula sobre las citas salientes de ese corpus
    (los citados pueden ser fundamentos fuera del corpus).
    """
    edges = build_edges(conn, citer_ids=article_ids)
    if not edges and article_ids is not None:
        edges = build_edges(conn, citer_ids=None)
    if not edges:
        return []

    # Cargar metadatos de artículos involucrados
    node_ids = set()
    for citer, cited in edges:
        node_ids.add(citer)
        node_ids.add(cited)

    placeholders = ",".join(["?"] * len(node_ids))
    rows = conn.execute(
        f"SELECT id, title, doi, year, journal_title, cited_by FROM articles WHERE id IN ({placeholders})",
        list(node_ids),
    ).fetchall()
    nodes_info = {r["id"]: dict(r) for r in rows}

    # Dirección temporal: cited (pasado) -> citer (presente)
    # Para evitar ciclos anómalos por citas cruzadas o años iguales, ordenamos por (year, id)
    temporal_edges: list[tuple[int, int]] = []
    adj_out: dict[int, list[int]] = defaultdict(list)
    adj_in: dict[int, list[int]] = defaultdict(list)

    for citer, cited in edges:
        info_citer = nodes_info.get(citer)
        info_cited = nodes_info.get(cited)
        if not info_citer or not info_cited:
            continue
        y_citer = info_citer.get("year") or 2026
        y_cited = info_cited.get("year") or 2000
        # El flujo temporal del conocimiento va del citado al que cita
        if y_citer >= y_cited:
            temporal_edges.append((cited, citer))
            adj_out[cited].append(citer)
            adj_in[citer].append(cited)

    if not temporal_edges:
        return []

    # Orden topológico aproximado basado en año cronológico
    sorted_nodes = sorted(
        list(node_ids),
        key=lambda nid: (nodes_info.get(nid, {}).get("year") or 2000, nid),
    )

    # N_sources: número de trayectorias desde cualquier origen hasta u
    n_sources: dict[int, int] = defaultdict(int)
    for u in sorted_nodes:
        preds = adj_in.get(u, [])
        if not preds:
            n_sources[u] = 1
        else:
            n_sources[u] = sum(n_sources[p] for p in preds)

    # N_sinks: número de trayectorias desde v hasta cualquier destino
    n_sinks: dict[int, int] = defaultdict(int)
    for v in reversed(sorted_nodes):
        succs = adj_out.get(v, [])
        if not succs:
            n_sinks[v] = 1
        else:
            n_sinks[v] = sum(n_sinks[s] for s in succs)

    # Calcular Search Path Count (SPC) para cada arista: N_sources(u) * N_sinks(v)
    spc_weights: list[dict] = []
    for u, v in temporal_edges:
        weight = n_sources.get(u, 1) * n_sinks.get(v, 1)
        info_u = nodes_info.get(u, {})
        info_v = nodes_info.get(v, {})
        y_u = info_u.get("year")
        y_v = info_v.get("year")
        spc_weights.append({
            "source_id": u,
            "target_id": v,
            "source": {
                "id": u,
                "doi": info_u.get("doi"),
                "title": info_u.get("title"),
                "year": y_u,
                "journal": info_u.get("journal_title"),
                "role": classify_epistemic_role(info_u),
            },
            "target": {
                "id": v,
                "doi": info_v.get("doi"),
                "title": info_v.get("title"),
                "year": y_v,
                "journal": info_v.get("journal_title"),
                "role": classify_epistemic_role(info_v),
            },
            "spc_weight": weight,
            "year_gap": (y_v - y_u) if (y_v and y_u) else 0,
        })

    spc_weights.sort(key=lambda x: -x["spc_weight"])
    return spc_weights[:top_n]


def classify_epistemic_role(
    article: dict,
    indegree: int = 0,
    cited_by_p90: int | None = None,
    ref_count_p90: int | None = None,
) -> str:
    """Clasifica el rol epistemológico de un artículo según heurísticas bibliométricas.

    Roles:
    - Synthesis/Review: Meta-análisis, revisiones sistemáticas, estados del arte.
    - Methodological: Validación de instrumentos, escalas, protocolos, metodologías.
    - Theoretical/Framework: Alta densidad conceptual o marcos teóricos fundacionales.
    - Seminal: Obras clásicas con alto impacto / citas acumuladas.
    - Empirical: Estudios de caso, trabajo empírico y análisis aplicados (por defecto).

    Los umbrales de cited_by y ref_count son adaptativos: se usan percentiles del
    catálogo si se proporcionan, o fallback a constantes razonables.
    """
    title = (article.get("title") or "").lower()
    abstract = (article.get("abstract") or "").lower()
    text = f"{title} {abstract}"

    cited_by = article.get("cited_by") or 0
    ref_count = 0
    for col in ("referenced_ids", "s2_references", "referenced_works"):
        val = article.get(col)
        if isinstance(val, list):
            ref_count = max(ref_count, len(val))
        elif isinstance(val, str):
            try:
                ref_count = max(ref_count, len(json.loads(val)))
            except Exception:
                pass

    # Umbrales adaptativos (percentil 90 del catálogo) o fallback a constantes
    seminal_threshold = cited_by_p90 if cited_by_p90 is not None else 40
    theoretical_threshold = ref_count_p90 if ref_count_p90 is not None else 70

    if any(k in title for k in [
        "review", "revisión", "revisão", "systematic", "scoping", "meta-analysis", "metaanálisis", "metanálise", 
        "estado de la cuestión", "estado del arte", "estado da arte", "survey", "overview",
        "bibliométric", "cienciométric", "mapeo", "mapping", "síntesis", "synthesis"
    ]) or any(k in text for k in [
        "revisión sistemática", "scoping review", "análisis bibliométrico", "mapeo sistemático", 
        "revisión de la literatura", "revisión bibliográfica", "revisión integrativa", "revisión narrativa",
        "revisão sistemática", "revisão de literatura", "revisão integrativa", "literature review",
        "systematic review", "integrative review"
    ]):
        return "Synthesis/Review"

    if any(k in title for k in [
        "metodología", "methodology", "metodologia", "psychometric", "psicométric", "instrument", "instrumento",
        "escala", "scale", "validación", "validation", "validação", "protocol", "protocolo", "measurement", 
        "medición", "medição", "rúbrica", "cuestionario", "questionário", "experimental", "trial", "clinical trial",
        "ensayo clínico", "ensaio clínico", "cohorte", "cohort"
    ]) or any(k in text for k in [
        "propiedades psicométricas", "construcción y validación", "confiabilidad y validez", 
        "adaptación transcultural", "análisis factorial", "diseño experimental", "método cualitativo", 
        "método cuantitativo", "estudio longitudinal", "estudio de cohorte", "estudo de coorte", 
        "validez y confiabilidad", "propriedades psicométricas", "adaptação transcultural", "randomized controlled trial", "rct"
    ]):
        return "Methodological"

    if any(k in title for k in [
        "perspectiva", "perspective", "reflexiones", "reflexión", "reflexão", "ensayo", "essay", "modelo", "model",
        "propuesta", "proposal", "proposta", "fundamentos", "foundations", "epistemolog", "paradigma", "paradigm", 
        "mirada", "ontología", "ontology", "fenomenología", "phenomenology", "teoría", "theory", "teoria"
    ]) or any(k in text for k in [
        "marco teórico", "conceptual framework", "epistemolog", "theoretical framework",
        "perspectiva teórica", "reflexiones acerca de", "ensayo teórico", "propuesta conceptual",
        "modelo teórico", "fundamentos teóricos", "debate teórico", "enfoque conceptual",
        "teoría fundamentada", "grounded theory", "teoria fundamentada", "referencial teórico", 
        "marco conceitual", "fundamentación", "conceptual model", "theoretical model"
    ]) or ref_count >= theoretical_threshold:
        return "Theoretical/Framework"

    if cited_by >= seminal_threshold or indegree >= 5:
        return "Seminal"

    return "Empirical"


def catalog_percentiles(conn: sqlite3.Connection, percentile: float = 0.90) -> dict:
    """Calcula percentiles de cited_by y ref_count del catálogo para umbrales adaptativos."""
    cited_values = []
    ref_counts = []
    for r in conn.execute("SELECT cited_by, referenced_ids, s2_references FROM articles").fetchall():
        cited_values.append(r["cited_by"] or 0)
        rc = 0
        for col in ("referenced_ids", "s2_references"):
            try:
                rc = max(rc, len(json.loads(r[col] or "[]")))
            except Exception:
                pass
        ref_counts.append(rc)
    if not cited_values:
        return {"cited_by_p90": 40, "ref_count_p90": 70}
    cited_values.sort()
    ref_counts.sort()
    idx = max(0, int(len(cited_values) * percentile) - 1)
    return {
        "cited_by_p90": max(cited_values[idx], 10),
        "ref_count_p90": max(ref_counts[min(idx, len(ref_counts) - 1)], 30),
    }


def curate_roles(conn: sqlite3.Connection, dois: list[str] | None = None, limit: int = 50) -> list[dict]:
    """Curación sistemática: clasifica papers por su rol epistemológico y centralidad."""
    edges = build_edges(conn)
    indeg: dict[int, int] = {}
    outdeg: dict[int, int] = {}
    for a, b in edges:
        outdeg[a] = outdeg.get(a, 0) + 1
        indeg[b] = indeg.get(b, 0) + 1

    # Umbrales adaptativos basados en la distribución real del catálogo
    pcts = catalog_percentiles(conn)

    rows = []
    if dois:
        flat_dois: list[str] = []
        for d in dois:
            if not d:
                continue
            for part in str(d).split(","):
                part_clean = clean_doi(part)
                if part_clean:
                    flat_dois.append(part_clean)

        if flat_dois:
            placeholders = ",".join(["?"] * len(flat_dois))
            rows = conn.execute(
                f"SELECT id, title, doi, year, journal_title, cited_by, abstract, authors, url, keywords, source, referenced_ids, s2_references FROM articles WHERE LOWER(doi) IN ({placeholders})",
                flat_dois,
            ).fetchall()

    if not rows and not dois:
        return []

    results = []
    for r in rows:
        art = dict(r)
        aid = art["id"]
        role = classify_epistemic_role(
            art,
            indegree=indeg.get(aid, 0),
            cited_by_p90=pcts["cited_by_p90"],
            ref_count_p90=pcts["ref_count_p90"],
        )
        authors_raw = art.get("authors")
        parsed_authors = []
        if authors_raw:
            try:
                parsed_authors = json.loads(authors_raw) if isinstance(authors_raw, str) else authors_raw
            except Exception:
                parsed_authors = [authors_raw]

        results.append({
            "id": aid,
            "doi": art.get("doi"),
            "title": art.get("title"),
            "year": art.get("year"),
            "journal": art.get("journal_title"),
            "role": role,
            "source": art.get("source") or "openalex",
            "abstract": art.get("abstract") or "",
            "authors": parsed_authors,
            "url": art.get("url") or "",
            "cited_by_global": art.get("cited_by") or 0,
            "indegree_catalog": indeg.get(aid, 0),
            "outdegree_catalog": outdeg.get(aid, 0),
        })

    return results


def find_epistemic_bridges(
    conn: sqlite3.Connection,
    cluster_a_dois: list[str],
    cluster_b_dois: list[str],
    limit: int = 15,
) -> list[dict]:
    """Identifica artículos bisagra / 'puentes epistemológicos' entre dos comunidades o escuelas.

    Un puente es una obra que conecta ambos clústeres al citar o ser citado simultáneamente
    por miembros de ambas comunidades.
    """
    idx = build_index(conn)
    set_a_ids = {idx.get(f"doi:{d.strip().lower()}") for d in cluster_a_dois if d and idx.get(f"doi:{d.strip().lower()}")}
    set_b_ids = {idx.get(f"doi:{d.strip().lower()}") for d in cluster_b_dois if d and idx.get(f"doi:{d.strip().lower()}")}

    if not set_a_ids or not set_b_ids:
        return []

    edges = build_edges(conn)
    # Mapear conexiones por cada nodo: citer -> cited
    cites: dict[int, set[int]] = defaultdict(set)
    cited_by: dict[int, set[int]] = defaultdict(set)
    for citer, cited in edges:
        cites[citer].add(cited)
        cited_by[cited].add(citer)

    all_nodes = set(cites.keys()) | set(cited_by.keys())
    bridge_candidates: list[dict] = []

    for nid in all_nodes:
        # Relaciones con A
        a_cited = cites[nid] & set_a_ids
        a_citing = cited_by[nid] & set_a_ids
        total_a = len(a_cited) + len(a_citing)

        # Relaciones con B
        b_cited = cites[nid] & set_b_ids
        b_citing = cited_by[nid] & set_b_ids
        total_b = len(b_cited) + len(b_citing)

        if total_a > 0 and total_b > 0:
            # Score balanceado de intermediación
            score = (total_a * total_b) + (total_a + total_b)
            bridge_candidates.append({
                "article_id": nid,
                "score": score,
                "links_to_cluster_a": total_a,
                "links_to_cluster_b": total_b,
                "in_cluster_a": nid in set_a_ids,
                "in_cluster_b": nid in set_b_ids,
            })

    bridge_candidates.sort(key=lambda x: -x["score"])
    top = bridge_candidates[:limit]

    out = []
    for cand in top:
        row = conn.execute(
            "SELECT id, title, doi, year, journal_title, cited_by FROM articles WHERE id = ?",
            (cand["article_id"],),
        ).fetchone()
        if row:
            art = dict(row)
            art["role"] = classify_epistemic_role(art)
            out.append({**art, **cand})

    return out


def expand_seed_graph(
    conn: sqlite3.Connection,
    seed_doi: str,
    direction: str = "both",
    limit: int = 25,
    live: bool = True,
) -> dict:
    """Expansión Snowballing backward/forward a partir de un paper semilla.

    Combina dos fuentes:

    - **Aristas internas** del catálogo (referencias ya depositadas).
    - **OpenAlex en vivo** (si `live`): las referencias del semilla (`referenced_works`) y las
      obras que lo citan (`cites:`).

    La vía en vivo es lo que faltaba: medido el 22-09-2026, sin ella el snowballing devolvía
    **solo la semilla** (6/6 semillas -> `expandidos=1`) porque solo caminaba por citas internas
    y el catálogo apenas tiene referencias (15%).
    """
    import httpx

    from . import config, db
    from .harvester import openalex

    idx = build_index(conn)
    norm_doi = clean_doi(seed_doi)
    seed_id = idx.get(f"doi:{norm_doi}") or idx.get(strip_oaid(seed_doi))
    if not seed_id and norm_doi:
        row = conn.execute(
            "SELECT id FROM articles WHERE LOWER(doi) = ? OR doi LIKE ? LIMIT 1",
            (norm_doi, f"%{norm_doi}%"),
        ).fetchone()
        if row:
            seed_id = row["id"]

    seed_openalex_id = None
    if seed_id:
        row = conn.execute("SELECT openalex_id FROM articles WHERE id = ?", (seed_id,)).fetchone()
        if row:
            seed_openalex_id = row["openalex_id"]

    cliente = None
    try:
        if live:
            cliente = httpx.Client(headers={"User-Agent": config.USER_AGENT},
                                   follow_redirects=True, timeout=20.0)

        # Semilla: resolver en vivo si falta (y obtener su id OpenAlex)
        if norm_doi and (not seed_id or not seed_openalex_id) and cliente is not None:
            item = openalex.get_work_by_doi(cliente, norm_doi)
            if item:
                art_obj = openalex.parse_item(item)
                if art_obj:
                    seed_openalex_id = art_obj.openalex_id or seed_openalex_id
                    if not seed_id:
                        _, seed_id = db.upsert_article(conn, art_obj.db_row())
                        idx = build_index(conn)

        if not seed_id:
            return {"error": f"DOI semilla '{seed_doi}' no encontrado en el catálogo ni en OpenAlex"}

        seed_row = conn.execute(
            "SELECT id, title, doi, year, journal_title, cited_by, referenced_ids, s2_references, "
            "openalex_id FROM articles WHERE id = ?",
            (seed_id,),
        ).fetchone()
        if not seed_row:
            return {"error": "Artículo no encontrado"}
        seed_art = dict(seed_row)
        seed_art["role"] = classify_epistemic_role(seed_art)
        seed_art["is_seed"] = True

        def _clave(a: dict) -> str:
            return (clean_doi(a.get("doi")) or a.get("openalex_id")
                    or (a.get("title") or "")[:60].lower())

        nodos: dict[str, dict] = {_clave(seed_art): seed_art}
        sub_edges: list[dict] = []

        # ---- Aristas internas (catálogo) ----
        citer_to_cited: dict[int, set[int]] = defaultdict(set)
        cited_to_citer: dict[int, set[int]] = defaultdict(set)
        for citer, cited in build_edges(conn):
            citer_to_cited[citer].add(cited)
            cited_to_citer[cited].add(citer)

        def _interno(aid: int, relation: str) -> dict | None:
            r = conn.execute(
                "SELECT id, title, doi, year, journal_title, cited_by, openalex_id FROM articles WHERE id = ?",
                (aid,),
            ).fetchone()
            if not r:
                return None
            a = dict(r)
            a["relation"] = relation
            a["role"] = classify_epistemic_role(a)
            return a

        if direction in ("backward", "both"):
            for aid in list(citer_to_cited.get(seed_id, set()))[:limit]:
                a = _interno(aid, "cited_by_seed (ancestor)")
                if a:
                    nodos.setdefault(_clave(a), a)
                    sub_edges.append({"source_id": aid, "target_id": seed_id})
        if direction in ("forward", "both"):
            for aid in list(cited_to_citer.get(seed_id, set()))[:limit]:
                a = _interno(aid, "cites_seed (descendant)")
                if a:
                    nodos.setdefault(_clave(a), a)
                    sub_edges.append({"source_id": seed_id, "target_id": aid})

        # ---- OpenAlex en vivo (lo que hace que el snowballing funcione) ----
        if cliente is not None and seed_openalex_id:
            if direction in ("backward", "both"):
                try:
                    refs = json.loads(seed_art.get("referenced_ids") or "[]")
                except (json.JSONDecodeError, TypeError):
                    refs = []
                if not refs:
                    item = openalex.get_work_by_doi(cliente, norm_doi)
                    refs = [(x or "").replace("https://openalex.org/", "").strip()
                            for x in ((item or {}).get("referenced_works") or []) if x]
                for it in openalex.get_works_by_ids(cliente, refs[:limit]):
                    art = openalex.parse_item(it)
                    if not art:
                        continue
                    a = art.db_row()
                    a["relation"] = "cited_by_seed (ancestor)"
                    a["role"] = classify_epistemic_role(a)
                    nodos.setdefault(_clave(a), a)
                    sub_edges.append({"source_doi": a.get("doi"), "target_doi": seed_art.get("doi")})
            if direction in ("forward", "both"):
                for it in openalex.get_citing_works(cliente, seed_openalex_id, limit=limit):
                    art = openalex.parse_item(it)
                    if not art:
                        continue
                    a = art.db_row()
                    a["relation"] = "cites_seed (descendant)"
                    a["role"] = classify_epistemic_role(a)
                    nodos.setdefault(_clave(a), a)
                    sub_edges.append({"source_doi": seed_art.get("doi"), "target_doi": a.get("doi")})
    finally:
        if cliente is not None:
            cliente.close()

    return {
        "seed": seed_art,
        "direction": direction,
        "expanded_count": len(nodos),
        "articles": list(nodos.values()),
        "network_edges": sub_edges,
    }


def get_similar_by_references(conn: sqlite3.Connection, doi: str, limit: int = 15) -> list[dict]:
    """Calcula la similitud de acoplamiento bibliográfico (Jaccard) según referencias compartidas."""
    idx = build_index(conn)
    target_id = idx.get(f"doi:{doi.strip().lower()}") or idx.get(strip_oaid(doi))
    if not target_id:
        return []

    row = conn.execute("SELECT referenced_ids, s2_references FROM articles WHERE id = ?", (target_id,)).fetchone()
    if not row:
        return []

    keys = set()
    for col in ("referenced_ids", "s2_references"):
        try:
            keys |= _ref_keys(json.loads(row[col] or "[]"))
        except (json.JSONDecodeError, TypeError):
            continue

    if not keys:
        return []

    results = []
    rows = conn.execute("SELECT id, title, doi, year, journal_title, cited_by, referenced_ids, s2_references FROM articles WHERE id != ?", (target_id,)).fetchall()
    for r in rows:
        rk = set()
        for col in ("referenced_ids", "s2_references"):
            try:
                rk |= _ref_keys(json.loads(r[col] or "[]"))
            except (json.JSONDecodeError, TypeError):
                continue
        inter = len(keys & rk)
        if inter > 0:
            union = len(keys | rk)
            jaccard = round(inter / union, 4) if union > 0 else 0
            art = {
                "id": r["id"],
                "title": r["title"],
                "doi": r["doi"],
                "year": r["year"],
                "journal": r["journal_title"],
                "cited_by": r["cited_by"],
                "shared_refs": inter,
                "jaccard_similarity": jaccard,
            }
            art["role"] = classify_epistemic_role(art)
            results.append(art)

    results.sort(key=lambda x: (-x["jaccard_similarity"], -x["shared_refs"]))
    return results[:limit]