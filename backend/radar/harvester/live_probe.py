"""Sonda en Vivo Federada de Thinkuy (OpenAlex, OpenAIRE Graph v3, Dialnet Dismax).

Permite al radar explorar cualquier campo del conocimiento humano en tiempo real
consultando en paralelo múltiples fuentes globales, europeas e iberoamericanas.
Calcula al vuelo la radiografía bibliométrica:
- Total de documentos indexados en el mundo
- Revistas núcleo donde se concentra la discusión
- Autores articuladores y años de publicación
- Muestra de artículos para el Auditor Epistémico y el Screening PRISMA-ScR
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

import httpx

from ..normalize import norm
from . import dialnet, openaire, openalex

log = logging.getLogger("radar.live_probe")

OPENALEX_WORKS_URL = "https://api.openalex.org/works"


def _probe_openalex(query: str, limit: int = 15, timeout: float = 12.0) -> tuple[list[dict[str, Any]], int]:
    """Consulta directa a OpenAlex Works API."""
    clean_q = " ".join(query.split()).strip()
    has_boolean = any(op in clean_q for op in (" AND ", " OR ", " NOT ", '"', "(", ")"))
    if has_boolean:
        params: dict[str, Any] = {
            "filter": f"title_and_abstract.search:{clean_q},is_oa:true",
            "per-page": limit,
            "sort": "relevance_score:desc",
        }
    else:
        params: dict[str, Any] = {
            "search": clean_q,
            "filter": "is_oa:true",
            "per-page": limit,
            "sort": "relevance_score:desc",
        }
    headers = {
        "User-Agent": "mailto:info@thinkuy.org (Thinkuy Scientific Radar; https://thinkuy.org)",
        "Accept": "application/json",
    }
    from .. import config as _cfg
    if _cfg.OPENALEX_API_KEY:
        headers["Authorization"] = f"Bearer {_cfg.OPENALEX_API_KEY}"

    articles: list[dict[str, Any]] = []
    total = 0
    page_size = min(limit, 100)
    params["per-page"] = page_size
    current_page = 1
    try:
        with httpx.Client(timeout=timeout) as client:
            while len(articles) < limit:
                params["page"] = current_page
                resp = client.get(OPENALEX_WORKS_URL, params=params, headers=headers)
                if resp.status_code != 200:
                    log.warning("Sonda OpenAlex HTTP %d: %s", resp.status_code, resp.text[:120])
                    break
                data = resp.json()
                results = data.get("results") or []
                total = int(data.get("meta", {}).get("count") or total or len(results))
                if not results:
                    break
                for item in results:
                    art_obj = openalex.parse_item(item)
                    if not art_obj:
                        continue
                    art = art_obj.to_dict()
                    art["source_engine"] = "openalex"
                    art["match_score"] = int(round((item.get("relevance_score") or 1.0) * 10))
                    art["matched"] = [{"keyword": query, "field": "global_openalex", "weight": art["match_score"]}]
                    art["conversation"] = {
                        "score": art["match_score"],
                        "why": ["Recuperado en tiempo real por Sonda Abierta OpenAlex (Global)"],
                        "signal": "sonda_en_vivo",
                    }
                    articles.append(art)
                    if len(articles) >= limit:
                        break
                current_page += 1
                if current_page > 10:
                    break
    except Exception as e:
        log.warning("Fallo al contactar Sonda OpenAlex: %s", e)

    return articles, total


def _probe_openaire(query: str, limit: int = 15, timeout: float = 12.0) -> list[dict[str, Any]]:
    """Consulta directa a OpenAIRE Graph v3."""
    articles: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=timeout) as client:
            found = openaire.search(client=client, query=query, limit=limit, timeout=timeout)
            for f in found:
                art = f.to_dict()
                art["source"] = "openaire"
                art["source_engine"] = "openaire"
                art["match_score"] = 8
                art["matched"] = [{"keyword": query, "field": "openaire_graph", "weight": 8}]
                art["conversation"] = {
                    "score": 8,
                    "why": ["Recuperado en tiempo real por Sonda OpenAIRE Graph v3 (Políticas & Proyectos UE)"],
                    "signal": "sonda_en_vivo",
                }
                articles.append(art)
    except Exception as e:
        log.warning("Fallo al contactar Sonda OpenAIRE: %s", e)
    return articles


def _probe_dialnet(query: str, limit: int = 15, timeout: float = 12.0) -> list[dict[str, Any]]:
    """Consulta directa a Dialnet Dismax."""
    articles: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=timeout) as client:
            found = dialnet.search(client=client, query=query, limit=limit, timeout=timeout)
            for f in found:
                art = f.to_dict()
                art["source"] = "dialnet"
                art["source_engine"] = "dialnet"
                art["match_score"] = 8
                art["matched"] = [{"keyword": query, "field": "dialnet_dismax", "weight": 8}]
                art["conversation"] = {
                    "score": 8,
                    "why": ["Recuperado en tiempo real por Sonda Dialnet (España / Iberoamérica)"],
                    "signal": "sonda_en_vivo",
                }
                articles.append(art)
    except Exception as e:
        log.warning("Fallo al contactar Sonda Dialnet: %s", e)
    return articles


# Andamiaje de la pregunta: interrogativos, nexos y verbos de consulta. NO incluye los
# sustantivos del dominio (instrumento, escala, percepción, salud): esos son justamente los
# términos que hay que buscar.
_ANDAMIAJE = frozenset({
    "que", "qué", "cual", "cuál", "cuales", "cuáles", "como", "cómo", "cuanto", "cuánto",
    "cuanta", "cuánta", "donde", "dónde", "cuando", "cuándo", "quien", "quién", "porque",
    "para", "por", "con", "sin", "sobre", "entre", "desde", "hasta", "del", "los", "las",
    "una", "unos", "unas", "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas",
    "utiliza", "utilizan", "valora", "valorar", "evalua", "evaluar", "mide", "medir",
    "sirve", "existe", "existen", "tiene", "tienen", "puede", "pueden", "debe", "deben",
    "aplica", "aplicar", "emplea", "emplear", "conoce", "conocer", "papel", "manera",
})

# Número de escalones que construye la escalera (compuestas + términos sueltos). Lo que se
# SONDEA está acotado aparte: hasta 4 formulaciones compuestas y 3 términos sueltos.
MAX_INTENTOS = 8


def _terminos_de_contenido(texto: str, maximo: int = 12) -> list[str]:
    """Palabras con carga semántica, en orden de aparición y sin repetir.

    El tope es 12 y no 8: con 8, una pregunta larga dejaba fuera justamente los términos
    discriminantes del final («percepción», «salud», «miocarditis») y el último escalón caía
    en palabras genéricas del principio. Se midió con la pregunta clínica del IP.
    """
    salida: list[str] = []
    for palabra in re.findall(r"[a-záéíóúüñç]{4,}", (texto or "").lower()):
        if palabra in _ANDAMIAJE or palabra in salida:
            continue
        salida.append(palabra)
    return salida[:maximo]


def escalera_de_consultas(query: str, compound_keywords: list[str] | None = None,
                          maximo: int = MAX_INTENTOS) -> list[str]:
    """Escalera de intentos: de la consulta más estricta a la más relajada.

    Motivo medido (18-09-2026): OpenAlex trata el `search` como una conjunción de todos los
    términos, de modo que una pregunta larga devuelve **cero**. Medido con la pregunta de un
    investigador: las 9 palabras dieron 0 obras, mientras «escala percepción salud» dio
    111.172 y «miocarditis» 4.352. La solución no es adivinar mejor, sino **reintentar
    relajando** y declarar con qué consulta se encontró.
    """
    terminos = [k.strip() for k in (compound_keywords or []) if k and k.strip()]
    consulta = (query or "").strip()

    escalera: list[str] = []
    if terminos:
        escalera.append(" ".join(terminos))
    if consulta and consulta not in escalera:
        escalera.append(consulta)

    contenido = _terminos_de_contenido(" ".join(terminos) + " " + consulta)
    if len(contenido) >= 3:
        escalera.append(" ".join(contenido[:4]))
    # Pares consecutivos: la combinación mínima que aún expresa una relación.
    for i in range(min(len(contenido) - 1, 3)):
        escalera.append(f"{contenido[i]} {contenido[i + 1]}")
    # Términos sueltos, del más largo al más corto (el más específico primero).
    for termino in sorted(contenido, key=len, reverse=True)[:3]:
        escalera.append(termino)

    vistas: set[str] = set()
    unicas: list[str] = []
    for intento in escalera:
        limpio = " ".join(intento.split())
        if limpio and limpio not in vistas:
            vistas.add(limpio)
            unicas.append(limpio)
    return unicas[:maximo]


def _probar_federacion(search_terms: str, limit: int, timeout: float,
                       federated: bool) -> tuple[list, int, list, list]:
    """Una pasada por las tres fuentes (OpenAlex, OpenAIRE, Dialnet) sin analizar nada."""
    raw_openalex: list[dict[str, Any]] = []
    openalex_total = 0
    raw_openaire: list[dict[str, Any]] = []
    raw_dialnet: list[dict[str, Any]] = []

    if federated:
        per_source_limit = max(int(limit * 0.8), 5)
        with ThreadPoolExecutor(max_workers=3) as executor:
            fut_oa = executor.submit(_probe_openalex, search_terms, per_source_limit, timeout)
            fut_aire = executor.submit(_probe_openaire, search_terms, per_source_limit, timeout)
            fut_dial = executor.submit(_probe_dialnet, search_terms, per_source_limit, timeout)
            try:
                raw_openalex, openalex_total = fut_oa.result()
            except Exception as e:
                log.warning("Error hilo OpenAlex: %s", e)
            try:
                raw_openaire = fut_aire.result()
            except Exception as e:
                log.warning("Error hilo OpenAIRE: %s", e)
            try:
                raw_dialnet = fut_dial.result()
            except Exception as e:
                log.warning("Error hilo Dialnet: %s", e)
    else:
        raw_openalex, openalex_total = _probe_openalex(search_terms, limit, timeout)

    return raw_openalex, openalex_total, raw_openaire, raw_dialnet


def probe_topic(query: str, compound_keywords: list[str] | None = None,
                limit: int = 15, timeout: float = 12.0,
                federated: bool = True) -> dict[str, Any] | None:
    """Ejecuta una sonda en vivo federada (OpenAlex, OpenAIRE Graph v3, Dialnet).

    **Relaja la consulta por escalones** hasta encontrar resultados, y declara con cuál lo
    hizo (`consulta_usada`, `relajada`, `intentos`). Si la consulta estricta ya da resultados,
    el comportamiento y el coste son los de siempre: un solo intento.

    Retorna un diccionario estructurado compatible con la auditoría de Thinkuy, o None si la
    consulta está vacía.
    """
    clean_q = query.strip()
    if not clean_q:
        return None

    escalones = escalera_de_consultas(clean_q, compound_keywords)
    multi = [e for e in escalones if len(e.split()) > 1]
    sueltos = [e for e in escalones if len(e.split()) == 1]

    intentos: list[dict[str, Any]] = []
    search_terms = ""
    raw_openalex: list[dict[str, Any]] = []
    openalex_total = 0
    raw_openaire: list[dict[str, Any]] = []
    raw_dialnet: list[dict[str, Any]] = []

    # FASE 1 — formulaciones con más de un término: se queda con la primera que dé resultados.
    for consulta in multi:
        oa, total_oa, aire, dial = _probar_federacion(consulta, limit, timeout, federated)
        encontrados = len(oa) + len(aire) + len(dial)
        intentos.append({"consulta": consulta, "resultados": encontrados})
        if encontrados:
            search_terms = consulta
            raw_openalex, openalex_total, raw_openaire, raw_dialnet = oa, total_oa, aire, dial
            break

    # FASE 2 — términos sueltos: si ninguna formulación compuesta funcionó, se sondean los
    # términos por separado (solo OpenAlex, que responde en décimas) y se elige **el más raro
    # con literatura**, que es el punto de entrada más enfocado frente a una palabra genérica.
    if not search_terms and sueltos:
        candidatos: list[tuple[int, str]] = []
        for termino in sueltos[:3]:
            oa_s, total_s = _probe_openalex(termino, 5, timeout)
            intentos.append({"consulta": termino, "resultados": len(oa_s),
                             "total_global": total_s, "sonda": "openalex"})
            if oa_s:
                candidatos.append((total_s or len(oa_s), termino))
        if candidatos:
            elegido = min(candidatos)[1]
            oa, total_oa, aire, dial = _probar_federacion(elegido, limit, timeout, federated)
            if len(oa) + len(aire) + len(dial):
                search_terms = elegido
                raw_openalex, openalex_total, raw_openaire, raw_dialnet = oa, total_oa, aire, dial

    relajada = len(intentos) > 1 and bool(intentos[-1]["resultados"])
    diagnostico = {
        "consulta_usada": search_terms or None,
        "relajada": relajada,
        "intentos": intentos,
    }

    if not search_terms:
        # Ningún escalón encontró nada: se declara la consulta estricta y lo intentado.
        search_terms = intentos[0]["consulta"] if intentos else clean_q
        log.info("Sonda sin resultados; intentos: %s", intentos)

    # Desduplicación unificada por DOI y título normalizado
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    articles: list[dict[str, Any]] = []

    source_counts = {"openalex": 0, "openaire": 0, "dialnet": 0}

    # Prioridad: OpenAlex (global metadata), OpenAIRE (EU policy/projects), Dialnet (Iberoamérica)
    for pool in (raw_openalex, raw_openaire, raw_dialnet):
        for art in pool:
            art_src = art.get("source") or art.get("source_engine") or "openalex"
            art["source"] = art_src
            art["source_engine"] = art_src

            t = norm(art.get("title") or "")
            if not t:
                continue

            d = (art.get("doi") or "").strip().lower()
            if d:
                if d in seen_dois:
                    continue
                seen_dois.add(d)

            if t in seen_titles:
                continue
            seen_titles.add(t)

            source_counts[art_src] = source_counts.get(art_src, 0) + 1
            articles.append(art)

    if not articles:
        # Ningún escalón encontró nada: se devuelve el diagnóstico de lo intentado en lugar de
        # None, para que la interfaz pueda decir QUÉ se buscó y no solo que no hubo resultados.
        return {
            "data_source": "live_probe",
            "probe_engine": "Sonda Federada: OpenAlex · OpenAIRE · Dialnet",
            "articles": [],
            "ecosystem": {"total_matched": 0,
                          "sources": {"openalex_live": 0, "openaire_live": 0, "dialnet_live": 0},
                          "top_journals": [], "years": {"min": None, "max": None, "recent_count": 0}},
            "saturation": {"level": "uncovered", "label": "Sin registros en tiempo real",
                           "description": "Ningún escalón de la consulta encontró publicaciones "
                                          "en acceso abierto en las bases globales.",
                           "review_count": 0},
            "top_authors": [],
            "suggested_keywords": [],
            **diagnostico,
        }

    # Total aproximado combinado
    total_matched = max(openalex_total, len(articles))

    journal_counts: dict[str, int] = {}
    author_data: dict[str, dict[str, Any]] = {}
    years_list: list[int] = []
    suggested_kw_counts: dict[str, int] = {}

    for art in articles:
        # Revistas / Contenedores
        jname = (art.get("journal_title") or "Publicación no declarada").strip()
        if jname:
            journal_counts[jname] = journal_counts.get(jname, 0) + 1

        # Años
        y_val = art.get("year") or (art.get("pub_date") or "")[:4]
        if y_val and str(y_val).isdigit():
            years_list.append(int(y_val))

        # Autores
        doi = art.get("doi") or ""
        for auth in (art.get("authors") or []):
            name = ""
            if isinstance(auth, dict):
                name = f"{auth.get('given', '')} {auth.get('family', '')}".strip() or str(auth.get("name") or "")
            elif isinstance(auth, str):
                name = auth.strip()
            if name and len(name) > 3:
                if name not in author_data:
                    author_data[name] = {"count": 0, "dois": []}
                author_data[name]["count"] += 1
                if doi and doi not in author_data[name]["dois"]:
                    author_data[name]["dois"].append(doi)

        # Conceptos y palabras clave sugeridas
        for kw in (art.get("keywords") or []):
            if isinstance(kw, str) and len(kw) > 3:
                suggested_kw_counts[kw] = suggested_kw_counts.get(kw, 0) + 1

    sorted_journals = sorted(journal_counts.items(), key=lambda x: -x[1])
    top_journals = [{"name": name, "count": count} for name, count in sorted_journals[:5]]

    sorted_authors = sorted(author_data.items(), key=lambda x: -x[1]["count"])
    top_authors = [{"name": name, "count": d["count"], "dois": d["dois"][:3]} for name, d in sorted_authors[:6]]

    sorted_suggested = sorted(suggested_kw_counts.items(), key=lambda x: -x[1])
    suggested_kws = [k for k, _ in sorted_suggested[:8]]

    year_min = min(years_list) if years_list else None
    year_max = max(years_list) if years_list else None
    recent_cutoff = date.today().year - 3
    recent_count = sum(1 for y in years_list if y >= recent_cutoff)

    # Diagnóstico de saturación para la literatura global
    if total_matched <= 15:
        sat_level = "niche"
        sat_label = "Frontera de Investigación Abierta / Vacío Temático"
        sat_desc = f"Baja densidad bibliográfica global en acceso abierto ({total_matched} obras). Terreno fértil con escasa competencia directa."
    elif total_matched <= 150:
        sat_level = "emerging"
        sat_label = "Campo Emergente en Crecimiento"
        sat_desc = f"Masa crítica intermedia ({total_matched} obras). Cuenta con antecedentes visibles y oportunidad de consolidación metodológica."
    else:
        sat_level = "saturated"
        sat_label = "Campo Científico Maduro / Altamente Denso"
        sat_desc = f"Alta densidad bibliográfica global ({total_matched} obras). Requiere formulaciones conceptuales específicas para diferenciarse del corpus existente."

    ecosystem_data = {
        "total_matched": total_matched,
        "sources": {
            "openalex_live": source_counts.get("openalex", 0),
            "openaire_live": source_counts.get("openaire", 0),
            "dialnet_live": source_counts.get("dialnet", 0),
        },
        "top_journals": top_journals,
        "years": {
            "min": year_min,
            "max": year_max,
            "recent_count": recent_count,
        },
    }

    saturation_data = {
        "level": sat_level,
        "label": sat_label,
        "description": sat_desc,
        "review_count": sum(1 for a in articles if any(t in (a.get("title") or "").lower() for t in ("review", "revisión", "scoping", "systematic"))),
    }

    return {
        "data_source": "live_probe",
        "probe_engine": "Sonda Federada: OpenAlex · OpenAIRE · Dialnet",
        "articles": articles,
        "ecosystem": ecosystem_data,
        "saturation": saturation_data,
        "top_authors": top_authors,
        "suggested_keywords": suggested_kws,
        **diagnostico,
    }

