"""Red Social de autores, fiel al modelo de Pajek (Batagelj & Mrvar).

Vértices = autores. Tres redes multiplex sobre los mismos vértices:
  1. Coautoría  -> edges (no dirigida), peso = nº de coautorías
  2. Citación   -> arcs  (dirigida),  peso = nº de citas A→B
  3. Revista    -> edges (no dirigida), peso = nº de revistas en común

Atributos de vértice al estilo Pajek:
  - Particiones (categóricas): sector temático dominante, comunidad (Louvain), k-core.
  - Vectores (numéricas): nº de obras, año de última publicación, grado,
    betweenness, closeness, hub/authority (HITS).

Medidas deterministas: grado, densidad, betweenness (Brandes), closeness,
HITS hubs/authorities (iteración de potencias), comunidades (modularidad),
k-cores (peeling).
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import defaultdict, deque

from . import db
from . import topics as topics_mod
from .conversation import strip_oaid
from .normalize import norm

# Caché en memoria para la red analizada
_NETWORK_CACHE: dict = {}
_NETWORK_CACHE_EXPIRY: float = 0.0
_NETWORK_CACHE_TTL: float = 300.0  # 5 minutos por defecto, invalidable manualmente
_EDGES_CACHE: dict = {}


def invalidate_network_cache():
    """Invalida la caché de la red social (útil tras una cosecha)."""
    global _NETWORK_CACHE, _NETWORK_CACHE_EXPIRY, _EDGES_CACHE
    _NETWORK_CACHE.clear()
    _NETWORK_CACHE_EXPIRY = 0.0
    _EDGES_CACHE.clear()


def _db_cache_token(conn: sqlite3.Connection) -> str:
    """Identifica la base de datos activa para evitar mezclar cachés entre campos."""
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
        return str(row[2]) if row and len(row) > 2 else "unknown-db"
    except Exception:
        return "unknown-db"


# ---------------------------------------------------------------- construcción

_TITLE_RE = re.compile(r"\b(dr|dra|phd|prof|msc|lic|mag|profesor|profesora)\b\.?", re.IGNORECASE)


def clean_author_name(given: str, family: str) -> tuple[str, str]:
    """Limpia títulos académicos de nombre y apellido."""
    g = _TITLE_RE.sub("", given or "").strip()
    f = _TITLE_RE.sub("", family or "").strip()
    g = re.sub(r"^\.|\.$", "", g).strip()
    f = re.sub(r"^\.|\.$", "", f).strip()
    return g, f


def normalize_orcid(raw: str | None) -> str | None:
    """Extrae y valida formato estándar de ORCID (0000-0000-0000-0000)."""
    if not raw:
        return None
    s = str(raw).replace("https://orcid.org/", "").replace("http://orcid.org/", "").strip()
    if re.match(r"^\d{4}-\d{4}-\d{4}-[\dX]{4}$", s, re.IGNORECASE):
        return s.upper()
    return None


def author_key(au: dict) -> str:
    given = str(au.get("given") or "").strip()
    family = str(au.get("family") or "").strip()
    g, f = clean_author_name(given, family)
    return norm(f"{f} {g}") if (g or f) else ""


def author_identity_map(articles: list[dict]) -> dict[str, set[str]]:
    """Mapa nombre normalizado -> ORCIDs observados en el corpus."""
    by_name: dict[str, set[str]] = defaultdict(set)
    for article in articles or []:
        for author in (article.get("authors") or []):
            if not isinstance(author, dict):
                continue
            given = str(author.get("given") or "").strip()
            family = str(author.get("family") or "").strip()
            cleaned_given, cleaned_family = clean_author_name(given, family)
            normalized = norm(f"{cleaned_family} {cleaned_given}") if (cleaned_given or cleaned_family) else ""
            orcid = normalize_orcid(author.get("orcid"))
            if normalized and orcid:
                by_name[normalized].add(orcid)
    return {name: set(orcids) for name, orcids in by_name.items()}


def _canonical_identity(author: dict, identity_map: dict[str, set[str]] | None = None) -> tuple[str, str | None, str]:
    """Identidad canónica determinista: ORCID directo, ORCID inferido, ambigua o sin verificar."""
    given = str(author.get("given") or "").strip()
    family = str(author.get("family") or "").strip()
    cleaned_given, cleaned_family = clean_author_name(given, family)
    normalized = norm(f"{cleaned_family} {cleaned_given}") if (cleaned_given or cleaned_family) else ""
    direct_orcid = normalize_orcid(author.get("orcid"))
    if direct_orcid:
        return f"orcid:{direct_orcid}", direct_orcid, "orcid-verified"
    known = (identity_map or {}).get(normalized, set()) if normalized else set()
    if len(known) == 1:
        only_orcid = next(iter(known))
        return f"orcid:{only_orcid}", only_orcid, "orcid-inferred"
    if len(known) > 1:
        return f"name:{normalized}:ambiguous", None, "ambiguous"
    return normalized, None, "unverified" if normalized else ""


def canonical_author_id(author: dict, identity_map: dict[str, set[str]] | None = None) -> str:
    """Clave estable de autor que prefiere ORCID y evita fusiones por homonimia."""
    canonical, _, _ = _canonical_identity(author, identity_map)
    return canonical


def _work_identifiers(a: dict) -> set[str]:
    """Conjunto de identidades del work (openalex id y doi) para resolver citas."""
    ids: set[str] = set()
    oid = strip_oaid(a.get("openalex_id") or (a.get("source_id") if a.get("source") == "openalex" else None))
    if oid:
        ids.add(oid)
    if a.get("doi"):
        ids.add(f"doi:{(a['doi']).strip().lower()}")
    return ids


def build_author_edges(conn: sqlite3.Connection, min_works: int = 1, include_terms: set[str] | None = None) -> dict:
    """Construye la red de autores. Devuelve dict con nodos y 3 relaciones."""
    normalized_include = {norm(term) for term in (include_terms or set()) if term and norm(term)}
    cache_key = (_db_cache_token(conn), min_works, tuple(sorted(normalized_include)))
    now = time.time()
    if cache_key in _EDGES_CACHE:
        cached_time, cached_res = _EDGES_CACHE[cache_key]
        if now - cached_time < 300.0:
            return cached_res

    rows = conn.execute("SELECT * FROM articles").fetchall()
    arts = [db._row_to_article(r) for r in rows]
    identity_map = author_identity_map(arts)

    authors: dict[str, dict] = {}          # key -> info agregada
    work_author: dict[str, set[str]] = {}  # identidad de work -> autores
    coauthor: dict[frozenset, int] = defaultdict(int)
    journal_edges: dict[frozenset, int] = defaultdict(int)

    # primera pasada: autores + obra
    for a in arts:
        for au in (a.get("authors") or []):
            if not isinstance(au, dict):
                continue
            key, orcid, identity_status = _canonical_identity(au, identity_map)
            if not key:
                continue
            g, f = clean_author_name(str(au.get("given") or ""), str(au.get("family") or ""))
            display_name = f"{g} {f}".strip() or key
            info = authors.setdefault(key, {
                "key": key,
                "name": display_name,
                "orcid": orcid,
                "identity_status": identity_status,
                "n": 0, "first": None, "last": None, "journals": set(),
                "field_counts": defaultdict(int),
            })
            if orcid and not info.get("orcid"):
                info["orcid"] = orcid
                info["identity_status"] = identity_status
            if len(display_name) > len(info["name"]) and not _TITLE_RE.search(display_name):
                info["name"] = display_name
            info["n"] += 1
            pd = a.get("pub_date") or (f"{a.get('year')}-01-01" if a.get("year") else "")
            if pd:
                info["first"] = pd if (info["first"] is None or pd < info["first"]) else info["first"]
                info["last"] = pd if (info["last"] is None or pd > info["last"]) else info["last"]
            if a.get("journal_title"):
                info["journals"].add(a["journal_title"])
            for f_item in topics_mod.classify_article_fields(a):
                info["field_counts"][f_item["id"]] += 1
            for wid in _work_identifiers(a):
                work_author.setdefault(wid, set()).add(key)

    # coautoría
    for a in arts:
        keys = [canonical_author_id(au, identity_map) for au in (a.get("authors") or []) if isinstance(au, dict)]
        keys = list(dict.fromkeys(k for k in keys if k))
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                coauthor[frozenset({keys[i], keys[j]})] += 1

    # revista compartida (vía índice invertido O(k^2) por revista, no O(N^2))
    journal_to_authors: dict[str, set[str]] = defaultdict(set)
    for key, info in authors.items():
        for jt in info["journals"]:
            journal_to_authors[jt].add(key)

    for jt, au_set in journal_to_authors.items():
        au_list = list(au_set)
        for i in range(len(au_list)):
            for j in range(i + 1, len(au_list)):
                journal_edges[frozenset({au_list[i], au_list[j]})] += 1

    # citación A→B (por obra citada resuelta a autores)
    citation: dict[tuple, int] = defaultdict(int)
    for a in arts:
        refs = set()
        for col in ("referenced_ids", "s2_references"):
            try:
                for x in a.get(col) or []:
                    s = str(x).strip()
                    if s.lower().startswith("doi:"):
                        refs.add(s.lower())
                    elif s.startswith("W"):
                        refs.add(strip_oaid(s))
                    elif s.startswith("http") or not s.isdigit():
                        refs.add(strip_oaid(s) or s)
            except (json.JSONDecodeError, TypeError):
                continue
        citer_keys = [canonical_author_id(au, identity_map) for au in (a.get("authors") or []) if isinstance(au, dict)]
        citer_keys = [k for k in citer_keys if k]
        for ref in refs:
            cited_keys = work_author.get(ref)
            if not cited_keys:
                continue
            for ck in citer_keys:
                for ck2 in cited_keys:
                    if ck != ck2:
                        citation[(ck, ck2)] += 1

    # filtrar por min_works, conservando autores solicitados explícitamente
    def _matches_include(key: str, info: dict) -> bool:
        candidates = {norm(key), norm(info.get("name") or ""), norm(info.get("orcid") or "")}
        return bool(candidates & normalized_include)

    keep = {k for k, v in authors.items() if v["n"] >= min_works}
    keep |= {k for k, v in authors.items() if v["n"] >= 1 and _matches_include(k, v)}
    coauthor = {e: w for e, w in coauthor.items() if e <= keep}
    journal_edges = {e: w for e, w in journal_edges.items() if e <= keep}
    citation = {e: w for e, w in citation.items() if e[0] in keep and e[1] in keep}

    # asignar sector dominante a cada autor
    for k, info in authors.items():
        if info["field_counts"]:
            dom = max(info["field_counts"].items(), key=lambda kv: kv[1])[0]
            info["sector"] = dom
        else:
            info["sector"] = "general"
        info["journals"] = sorted(info["journals"])[:12]

    res = {
        "authors": {k: v for k, v in authors.items() if k in keep},
        "coauthor": coauthor,
        "citation": citation,
        "journal": journal_edges,
        "identity_map": identity_map,
        "count": len(keep),
    }
    _EDGES_CACHE[cache_key] = (now, res)
    return res


# ---------------------------------------------------------------- SNA (Pajek)

def _undirected_graph(edges: dict) -> dict[str, set]:
    g: dict[str, set] = defaultdict(set)
    for e in edges:
        t = tuple(e) if isinstance(e, frozenset) else (e[0], e[1])
        if len(t) < 2:
            continue
        a, b = t
        g[a].add(b)
        g[b].add(a)
    return g


def _directed_graph(edges: dict) -> tuple[dict[str, set], dict[str, set]]:
    out: dict[str, set] = defaultdict(set)
    inc: dict[str, set] = defaultdict(set)
    for (a, b) in edges:
        out[a].add(b)
        inc[b].add(a)
    return out, inc


def degree(nodes: set, edges: dict) -> dict[str, dict]:
    g = _undirected_graph(edges)
    return {n: {"degree": len(g.get(n, set())),
                "in": len(g.get(n, set())),
                "out": len(g.get(n, set()))} for n in nodes}


def betweenness(nodes: set, edges: dict) -> dict[str, float]:
    """Betweenness (Brandes, no dirigido, no ponderado)."""
    g = _undirected_graph(edges)
    cb: dict[str, float] = defaultdict(float)
    for s in nodes:
        stack: list[str] = []
        pred: dict[str, list] = defaultdict(list)
        sigma: dict[str, float] = defaultdict(float)
        sigma[s] = 1.0
        dist: dict[str, int] = {s: 0}
        q = deque([s])
        while q:
            v = q.popleft()
            stack.append(v)
            for w in g.get(v, set()):
                if w not in dist:
                    dist[w] = dist[v] + 1
                    q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta: dict[str, float] = defaultdict(float)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w])
            if w != s:
                cb[w] += delta[w]
    n = max(len(nodes) - 1, 1)
    return {k: v / 2 / n for k, v in cb.items()} if n > 1 else {k: 0.0 for k in nodes}


def closeness(nodes: set, edges: dict) -> dict[str, float]:
    g = _undirected_graph(edges)
    res: dict[str, float] = {}
    for s in nodes:
        dist = {s: 0}
        q = deque([s])
        while q:
            v = q.popleft()
            for w in g.get(v, set()):
                if w not in dist:
                    dist[w] = dist[v] + 1
                    q.append(w)
        reachable = [d for k, d in dist.items() if k != s and d > 0]
        if reachable:
            res[s] = sum(reachable) / len(reachable) if sum(reachable) else 1.0
        else:
            res[s] = 0.0
    # normalizar: menor distancia media = más cercano → 1 - normalized
    mx = max((v for v in res.values()), default=1.0)
    return {k: (1.0 - v / mx) if mx else 0.0 for k, v in res.items()}


def hits(citation: dict, nodes: set, iters: int = 20) -> tuple[dict[str, float], dict[str, float]]:
    """HITS hubs/authorities sobre la red de citas dirigida."""
    outg, inc = _directed_graph(citation)
    nodes = [n for n in nodes]
    hub = {n: 1.0 for n in nodes}
    auth = {n: 1.0 for n in nodes}
    for _ in range(iters):
        auth = {n: sum(hub[m] for m in inc.get(n, set())) for n in nodes}
        hub = {n: sum(auth[m] for m in outg.get(n, set())) for n in nodes}
        na = sum(v ** 2 for v in auth.values()) ** 0.5 or 1
        nh = sum(v ** 2 for v in hub.values()) ** 0.5 or 1
        auth = {k: v / na for k, v in auth.items()}
        hub = {k: v / nh for k, v in hub.items()}
    return hub, auth


def communities(nodes: set, edges: dict, iters: int = 10) -> dict[str, int]:
    """Comunidades por propagación de etiquetas sobre la red no dirigida (rápida).

    Cada nodo adopta iterativamente la etiqueta más frecuente entre sus vecinos;
    los empates se resuelven con la etiqueta numéricamente menor (determinista).
    """
    g = _undirected_graph(edges)
    nodes = sorted(nodes)
    label = {n: i for i, n in enumerate(nodes)}
    for _ in range(iters):
        changed = False
        for n in nodes:
            neigh = g.get(n, set())
            if not neigh:
                continue
            counts: dict[int, int] = defaultdict(int)
            for m in neigh:
                counts[label[m]] += 1
            best = min((c for c in counts.items()), key=lambda kv: (-kv[1], kv[0]))[0]
            if best != label[n]:
                label[n] = best
                changed = True
        if not changed:
            break
    return label


def k_cores(nodes: set, edges: dict) -> dict[str, int]:
    """k-cores (peeling) sobre la red no dirigida (O(V+E))."""
    if not nodes:
        return {}
    g = _undirected_graph(edges)
    deg = {n: len(g.get(n, set())) for n in nodes}
    core: dict[str, int] = {}
    k = 0

    # Agrupar nodos por grado para extracción O(1)
    bucket: dict[int, set[str]] = defaultdict(set)
    for n, d in deg.items():
        bucket[d].add(n)

    remaining = len(nodes)
    while remaining > 0:
        # Encontrar el menor grado con nodos pendientes
        while k not in bucket or not bucket[k]:
            k += 1
            if k > max(deg.values(), default=0) + 1:
                break

        if k not in bucket or not bucket[k]:
            break

        n = bucket[k].pop()
        remaining -= 1
        core[n] = k

        # Actualizar vecinos activos
        for m in g.get(n, set()):
            if m not in core:
                old_deg = deg[m]
                if old_deg in bucket and m in bucket[old_deg]:
                    bucket[old_deg].remove(m)
                deg[m] -= 1
                new_deg = deg[m]
                bucket[new_deg].add(m)
                if new_deg < k:
                    k = new_deg

    for n in nodes:
        core.setdefault(n, 0)
    return core


def full_network(conn: sqlite3.Connection, min_works: int = 1) -> dict:
    """Ensambla la red completa con particiones y vectores (Pajek-ready), con caché."""
    global _NETWORK_CACHE, _NETWORK_CACHE_EXPIRY
    now = time.time()
    try:
        art_count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    except Exception:
        art_count = 0

    cache_key = (_db_cache_token(conn), min_works, art_count)
    if cache_key in _NETWORK_CACHE and now < _NETWORK_CACHE_EXPIRY:
        return _NETWORK_CACHE[cache_key]

    net = build_author_edges(conn, min_works=min_works)
    nodes = set(net["authors"].keys())
    deg = degree(nodes, net["coauthor"])
    btwn = betweenness(nodes, net["coauthor"])
    close = closeness(nodes, net["coauthor"])
    hub, auth = hits(net["citation"], nodes)
    comm = communities(nodes, net["coauthor"])
    cores = k_cores(nodes, net["coauthor"])

    sector_ids = {a["sector"] for a in net["authors"].values()}
    sector_map = {s: i + 1 for i, s in enumerate(sorted(sector_ids))}
    comm_ids = {c: i + 1 for i, c in enumerate(sorted(set(comm.values())))}

    vertices = []
    for key, info in net["authors"].items():
        vertices.append({
            "id": key,
            "name": info["name"],
            "orcid": info.get("orcid"),
            "identity_status": info.get("identity_status", "unverified"),
            "n": info["n"],
            "first_year": int((info["first"] or "")[:4]) if info.get("first") else None,
            "last_year": int((info["last"] or "")[:4]) if info.get("last") else None,
            "sector": info["sector"],
            "sector_id": sector_map[info["sector"]],
            "community": comm.get(key, 0),
            "community_id": comm_ids.get(comm.get(key, 0), 0),
            "k_core": cores.get(key, 0),
            "degree": deg.get(key, {}).get("degree", 0),
            "indegree": deg.get(key, {}).get("in", 0),
            "outdegree": deg.get(key, {}).get("out", 0),
            "betweenness": round(btwn.get(key, 0.0), 6),
            "closeness": round(close.get(key, 0.0), 6),
            "hub": round(hub.get(key, 0.0), 6),
            "authority": round(auth.get(key, 0.0), 6),
            "journals": info["journals"],
        })
    vertices.sort(key=lambda v: -v["n"])

    edges_out = []
    for (a, b), w in net["coauthor"].items():
        edges_out.append({"a": a, "b": b, "type": "coauthor", "weight": w})
    for (a, b), w in net["journal"].items():
        edges_out.append({"a": a, "b": b, "type": "journal", "weight": w})
    for (a, b), w in net["citation"].items():
        edges_out.append({"a": a, "b": b, "type": "citation", "weight": w})

    result = {
        "nodes": len(vertices),
        "edges": len(edges_out),
        "sectors": {k: v for v, k in sorted(sector_map.items(), key=lambda kv: kv[1])},
        "vertices": vertices,
        "lines": edges_out,
    }
    _NETWORK_CACHE[cache_key] = result
    _NETWORK_CACHE_EXPIRY = now + _NETWORK_CACHE_TTL
    return result


# ---------------------------------------------------------------- export Pajek (.net / .clu / .vec)

def _vertex_index(vertices: list[dict]) -> dict[str, int]:
    return {v["id"]: i + 1 for i, v in enumerate(vertices)}


def export_net(network: dict) -> str:
    verts = network["vertices"]
    idx = _vertex_index(verts)
    lines = [f"*Vertices {len(verts)}"]
    for v in verts:
        lines.append(f'{idx[v["id"]]} "{v["name"]}"')
    edges = [l for l in network["lines"] if l["type"] != "citation"]
    if edges:
        lines.append(f"*Edges {len(edges)}")
        for l in edges:
            lines.append(f'{idx[l["a"]]} {idx[l["b"]]} {l["weight"]}')
    arcs = [l for l in network["lines"] if l["type"] == "citation"]
    if arcs:
        lines.append(f"*Arcs {len(arcs)}")
        for l in arcs:
            lines.append(f'{idx[l["a"]]} {idx[l["b"]]} {l["weight"]}')
    return "\n".join(lines)


def export_clu(network: dict, what: str = "sector") -> str:
    verts = network["vertices"]
    key = "sector_id" if what == "sector" else "community_id"
    lines = [f"*Vertices {len(verts)}"]
    for v in verts:
        lines.append(str(v.get(key, 0)))
    return "\n".join(lines)


def export_vec(network: dict, field: str = "n") -> str:
    verts = network["vertices"]
    lines = [f"*Vertices {len(verts)}"]
    for v in verts:
        lines.append(str(v.get(field, 0)))
    return "\n".join(lines)