"""Mapeo Bibliométrico de Oportunidades Temáticas y Radar de Fronteras.

Motor de inteligencia editorial zero-alucinación:
1. Perfilado temático de revistas vía taxonomía Topics de OpenAlex (IDs únicos).
2. Cálculo determinista de Velocidad de Publicación (Relative Growth Rate) con umbral anti-ruido.
3. Identificación de Temas Consolidados, Temas Emergentes y Vacíos Editoriales (Gaps).
4. Búsqueda quirúrgica de académicos reales con identificador persistente ORCID verificado.
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Any, Dict, List, Optional
import httpx

from . import config

log = logging.getLogger("radar.editorial_radar")

OPENALEX_BASE = "https://api.openalex.org"
DEFAULT_MAILTO = getattr(config, "MAILTO", "info@thinkuy.org")

# Países del Sur Global e Iberoamérica prioritarios para el Radar OBCC
SUR_GLOBAL_CODES = [
    "AR", "BO", "BR", "CL", "CO", "CR", "CU", "DO", "EC", "ES",
    "GT", "HN", "MX", "NI", "PA", "PE", "PT", "PY", "SV", "UY",
    "VE", "ZA", "IN"
]
SUR_GLOBAL_PIPE = "|".join(SUR_GLOBAL_CODES)


def _clean_orcid(raw_orcid: Optional[str]) -> str:
    """Normaliza un ORCID a formato '0000-0000-0000-0000'."""
    if not raw_orcid:
        return ""
    val = raw_orcid.strip()
    for prefix in ("https://orcid.org/", "http://orcid.org/", "orcid.org/"):
        if val.startswith(prefix):
            val = val[len(prefix):]
    return val.strip()


def resolve_journal_source_openalex(
    query_or_issn: str,
    journal_title: Optional[str] = None,
    mailto: str = DEFAULT_MAILTO,
    timeout: float = 6.0,
) -> Optional[Dict[str, Any]]:
    """
    Busca la revista en OpenAlex Sources por ISSN exacto o por nombre/título.
    """
    clean_q = query_or_issn.strip()
    if not clean_q and not journal_title:
        return None

    # Si parece ISSN (e.g. 1134-3478 o 1028-4818)
    is_issn = False
    clean_issn = clean_q.replace(" ", "")
    if len(clean_issn) in (8, 9) and ("-" in clean_issn or clean_issn.isdigit()):
        is_issn = True

    headers = config.openalex_headers(f"Thinkuy-EditorialRadar/1.0 (mailto:{mailto})")
    params_mailto = {"mailto": mailto}

    with httpx.Client(timeout=timeout, headers=headers) as client:
        # 1. Intento por filtro ISSN
        if is_issn:
            try:
                resp = client.get(
                    f"{OPENALEX_BASE}/sources",
                    params={"filter": f"issn:{clean_issn}", **params_mailto},
                )
                if resp.status_code == 200:
                    results = resp.json().get("results") or []
                    if results:
                        return results[0]
            except Exception as e:
                log.warning("Fallo búsqueda ISSN OpenAlex para %s: %s", clean_issn, e)

        # 2. Búsqueda por texto (nombre / título de la revista o query)
        search_candidates = []
        if journal_title and journal_title.strip():
            search_candidates.append(journal_title.strip())
        if clean_q and not is_issn and clean_q not in search_candidates:
            search_candidates.append(clean_q)

        for text_cand in search_candidates:
            try:
                resp = client.get(
                    f"{OPENALEX_BASE}/sources",
                    params={"search": text_cand, **params_mailto},
                )
                if resp.status_code == 200:
                    results = resp.json().get("results") or []
                    if results:
                        # Preferir tipo 'journal'
                        for item in results:
                            if item.get("type") == "journal":
                                return item
                        return results[0]
            except Exception as e:
                log.warning("Fallo búsqueda por nombre OpenAlex para %s: %s", text_cand, e)

    return None


def compute_topic_velocity(
    topic_id: str,
    mailto: str = DEFAULT_MAILTO,
    min_vr_threshold: int = 40,
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Calcula la Tasa de Crecimiento Relativo (Relative Growth Rate / Velocidad)
    para un Topic de OpenAlex.

    Ventana reciente (Vr): 2024-2025 (2 años)
    Ventana base (Vb): 2021-2023 (3 años)
    Fórmula: Velocidad = (Vr / 2) / (Vb / 3)
    """
    clean_tid = topic_id.split("/")[-1]
    headers = config.openalex_headers(f"Thinkuy-EditorialRadar/1.0 (mailto:{mailto})")
    params_base = {"mailto": mailto, "per-page": 1}

    vr_count = 0
    vb_count = 0

    with httpx.Client(timeout=timeout, headers=headers) as client:
        try:
            r_vr = client.get(
                f"{OPENALEX_BASE}/works",
                params={"filter": f"topics.id:{clean_tid},publication_year:2024-2025", **params_base},
            )
            if r_vr.status_code == 200:
                vr_count = r_vr.json().get("meta", {}).get("count", 0)
        except Exception as e:
            log.warning("Error consultando Vr para topic %s: %s", clean_tid, e)

        try:
            r_vb = client.get(
                f"{OPENALEX_BASE}/works",
                params={"filter": f"topics.id:{clean_tid},publication_year:2021-2023", **params_base},
            )
            if r_vb.status_code == 200:
                vb_count = r_vb.json().get("meta", {}).get("count", 0)
        except Exception as e:
            log.warning("Error consultando Vb para topic %s: %s", clean_tid, e)

    if vb_count > 0:
        velocity = round((vr_count / 2.0) / (vb_count / 3.0), 2)
    else:
        velocity = round((vr_count / 2.0) if vr_count else 0.0, 2)

    # Clasificación con umbral mínimo de volumen para evitar ruido
    if vr_count < min_vr_threshold:
        classification = "vacio_nicho"
        badge_label = "🔍 Vacío / Nicho"
        interpretation = "Volumen global reducido para confirmar tendencia estadística."
    elif velocity > 1.4:
        classification = "emergente"
        badge_label = "🚀 Tema Emergente"
        interpretation = f"Aceleración atípica ({velocity}x). Alta dinámica de publicación reciente."
    elif 0.8 <= velocity <= 1.4:
        classification = "consolidado"
        badge_label = "🏷️ Tema Consolidado"
        interpretation = f"Estabilidad sostenida ({velocity}x). Núcleo tradicional de la disciplina."
    else:
        classification = "declive"
        badge_label = "📉 En Declive"
        interpretation = f"Velocidad decreciente ({velocity}x) o saturación temática."

    return {
        "topic_id": clean_tid,
        "vr_count": vr_count,
        "vb_count": vb_count,
        "velocity": velocity,
        "classification": classification,
        "badge_label": badge_label,
        "interpretation": interpretation,
    }


def get_verified_orcid_authors(
    topic_id: str,
    limit: int = 5,
    allowed_domains: Optional[set[str]] = None,
    allowed_fields: Optional[set[str]] = None,
    mailto: str = DEFAULT_MAILTO,
    timeout: float = 7.5,
    target_countries: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Recupera investigadores reales activos con ORCID verificado en el Topic,
    mediante el Protocolo Anti-Ruido Descendente de OpenAlex Works (2022-2026).
    Prioriza el ámbito Iberoamericano / Sur Global (OBCC) para fomentar redes
    regionales, garantizando que el autor tenga publicaciones recientes en el tema.
    """
    clean_tid = topic_id.split("/")[-1]
    countries = target_countries or SUR_GLOBAL_CODES
    pipe_countries = "|".join(countries)
    headers = config.openalex_headers(f"Thinkuy-EditorialRadar/1.0 (mailto:{mailto})")

    authors_found: Dict[str, Dict[str, Any]] = {}

    def _harvest_from_works(filter_query: str, per_page: int = 20):
        params = {
            "filter": filter_query,
            "sort": "cited_by_count:desc",
            "per-page": per_page,
            "mailto": mailto,
        }
        with httpx.Client(timeout=timeout, headers=headers) as client:
            try:
                resp = client.get(f"{OPENALEX_BASE}/works", params=params)
                if resp.status_code != 200:
                    return
                results = resp.json().get("results") or []
                for work in results:
                    work_title = work.get("title") or "Sin título"
                    work_year = work.get("publication_year")
                    work_cits = work.get("cited_by_count") or 0

                    for authorship in work.get("authorships") or []:
                        author = authorship.get("author") or {}
                        raw_orcid = author.get("orcid") or ""
                        clean_id = _clean_orcid(raw_orcid)
                        author_id = author.get("id")
                        if not clean_id or not author_id:
                            continue

                        # Extracción institucional y territorial
                        insts = authorship.get("institutions") or []
                        target_inst = None
                        if countries:
                            for inst in insts:
                                if inst.get("country_code") in countries:
                                    target_inst = inst
                                    break
                        if not target_inst and insts:
                            target_inst = insts[0]
                        if not target_inst:
                            target_inst = author.get("last_known_institution") or {}

                        c_code = target_inst.get("country_code") or "N/D"
                        affil_name = target_inst.get("display_name") or "Institución académica no especificada"

                        raw_name = author.get("display_name") or "Investigador"
                        clean_name = (
                            raw_name.replace("\u2010", "-")
                            .replace("\u2011", "-")
                            .replace("\u2012", "-")
                            .replace("\u2013", "-")
                            .replace("\u2014", "-")
                        )

                        if clean_id not in authors_found:
                            authors_found[clean_id] = {
                                "name": clean_name,
                                "orcid": clean_id,
                                "orcid_url": f"https://orcid.org/{clean_id}",
                                "affiliation": affil_name,
                                "country": c_code,
                                "works_count": 0,
                                "citations": work_cits,
                                "cited_by_count": work_cits,
                                "recent_works_count": 0,
                                "sample_work": work_title,
                                "sample_year": work_year,
                                "work_citations": work_cits,
                            }

                        cand = authors_found[clean_id]
                        cand["recent_works_count"] += 1
                        cand["works_count"] += 1
                        if work_cits >= cand["work_citations"]:
                            cand["sample_work"] = work_title
                            cand["sample_year"] = work_year
                            cand["work_citations"] = work_cits
                            cand["citations"] = max(cand["citations"], work_cits)
                            cand["cited_by_count"] = cand["citations"]
            except Exception as e:
                log.warning("Error en harvest de obras para topic %s: %s", clean_tid, e)

    # 1. Pase prioritario: Sur Global / Iberoamérica en obras recientes (2022-2026)
    _harvest_from_works(
        f"topics.id:{clean_tid},authorships.institutions.country_code:{pipe_countries},publication_year:2022-2026",
        per_page=min(max(limit * 4, 15), 25)
    )

    # 2. Pase de contingencia: si el tema no tiene suficientes autores en Sur Global, ampliar a global
    if len(authors_found) < limit:
        _harvest_from_works(
            f"topics.id:{clean_tid},publication_year:2022-2026",
            per_page=min(max(limit * 3, 10), 20)
        )

    # Ordenar por actividad reciente y citas del paper
    sorted_candidates = sorted(
        authors_found.values(),
        key=lambda x: (x["recent_works_count"], x["work_citations"]),
        reverse=True
    )
    return sorted_candidates[:limit]


def get_journal_community_authors(
    source_id: str,
    limit: int = 3,
    mailto: str = DEFAULT_MAILTO,
    timeout: float = 6.0,
) -> List[Dict[str, Any]]:
    """
    Recupera autores activos con ORCID verificado que han publicado recientemente
    en la propia revista (Comunidad Editorial Activa / Consejo Editorial natural).
    """
    clean_sid = source_id.split("/")[-1]
    headers = config.openalex_headers(f"Thinkuy-EditorialRadar/1.0 (mailto:{mailto})")
    params = {
        "filter": f"primary_location.source.id:{clean_sid},has_orcid:true,publication_year:2020-2026",
        "sort": "cited_by_count:desc",
        "per-page": 20,
        "mailto": mailto,
    }
    authors: List[Dict[str, Any]] = []
    seen_orcids = set()

    with httpx.Client(timeout=timeout, headers=headers) as client:
        try:
            resp = client.get(f"{OPENALEX_BASE}/works", params=params)
            if resp.status_code == 200:
                results = resp.json().get("results") or []
                for work in results:
                    w_title = work.get("title") or "Sin título"
                    w_year = work.get("publication_year")
                    w_cits = work.get("cited_by_count") or 0
                    for authorship in work.get("authorships") or []:
                        author = authorship.get("author") or {}
                        raw_orcid = author.get("orcid") or ""
                        clean_id = _clean_orcid(raw_orcid)
                        if not clean_id or clean_id in seen_orcids:
                            continue
                        seen_orcids.add(clean_id)

                        insts = authorship.get("institutions") or []
                        raw_strings = authorship.get("raw_affiliation_strings") or []
                        affil_name = ""
                        c_code = "N/D"

                        if insts:
                            target_inst = insts[0]
                            affil_name = target_inst.get("display_name") or ""
                            c_code = target_inst.get("country_code") or "N/D"

                        if not affil_name and raw_strings:
                            affil_name = raw_strings[0].strip()

                        if not affil_name:
                            lki = author.get("last_known_institution") or {}
                            affil_name = lki.get("display_name") or "Institución académica no especificada"
                            c_code = lki.get("country_code") or c_code

                        raw_name = author.get("display_name") or "Investigador"
                        clean_name = (
                            raw_name.replace("\u2010", "-")
                            .replace("\u2011", "-")
                            .replace("\u2012", "-")
                            .replace("\u2013", "-")
                            .replace("\u2014", "-")
                        )

                        authors.append({
                            "name": clean_name,
                            "orcid": clean_id,
                            "orcid_url": f"https://orcid.org/{clean_id}",
                            "affiliation": affil_name,
                            "country": c_code,
                            "works_count": 1,
                            "citations": w_cits,
                            "cited_by_count": w_cits,
                            "specialty_topic": "Comunidad Editorial (Autoría Reciente)",
                            "role_suggestion": "Comité Editorial / Revisor",
                            "sample_work": w_title,
                            "sample_year": w_year,
                        })
                        if len(authors) >= limit:
                            break
                    if len(authors) >= limit:
                        break
        except Exception as e:
            log.warning("Error recuperando comunidad de autores para source %s: %s", clean_sid, e)
    return authors


def run_editorial_bibliometric_mapping(
    query_or_issn: str,
    journal_title: Optional[str] = None,
    max_topics: int = 6,
    authors_per_topic: int = 3,
    mailto: str = DEFAULT_MAILTO,
) -> Dict[str, Any]:
    """
    Ejecuta el pipeline completo de 'Mapeo Bibliométrico de Oportunidades Temáticas':
    1. Identifica la revista y sus Topics en OpenAlex.
    2. Calcula velocidad y clasifica en Consolidados, Emergentes y Vacíos.
    3. Recupera académicos con ORCID verificado para los temas emergentes/vacíos.
    """
    source = resolve_journal_source_openalex(query_or_issn, journal_title=journal_title, mailto=mailto)
    if not source:
        return {
            "found": False,
            "query": query_or_issn,
            "error": f"No se encontró la publicación '{query_or_issn}' en el índice OpenAlex.",
            "consolidated_topics": [],
            "emerging_topics": [],
            "gap_topics": [],
            "suggested_reviewers": [],
        }

    journal_title = source.get("display_name") or query_or_issn
    issn_val = source.get("issn_l") or (source.get("issn") or ["N/D"])[0]
    raw_topics = source.get("topics") or []

    # Extraer dominios y campos de la revista para filtrar homónimos
    allowed_domains = {t.get("domain", {}).get("display_name") for t in raw_topics if t.get("domain")}
    allowed_fields = {t.get("field", {}).get("display_name") for t in raw_topics if t.get("field")}

    consolidated: List[Dict[str, Any]] = []
    emerging: List[Dict[str, Any]] = []
    gaps: List[Dict[str, Any]] = []
    reviewers_map: Dict[str, Dict[str, Any]] = {}

    for t in raw_topics[:max_topics]:
        t_id = t.get("id", "").split("/")[-1]
        t_name = t.get("display_name") or "Tema"
        journal_works_in_topic = t.get("count", 0)

        # Análisis de velocidad
        metrics = compute_topic_velocity(t_id, mailto=mailto)
        topic_entry = {
            "topic_id": t_id,
            "name": t_name,
            "subfield": (t.get("subfield") or {}).get("display_name", "General"),
            "field": (t.get("field") or {}).get("display_name", "Multidisciplinar"),
            "journal_works": journal_works_in_topic,
            "vr_count": metrics["vr_count"],
            "vb_count": metrics["vb_count"],
            "velocity": metrics["velocity"],
            "classification": metrics["classification"],
            "badge_label": metrics["badge_label"],
            "interpretation": metrics["interpretation"],
        }

        # Separar en categorías según la taxonomía y la dinámica
        cls = metrics["classification"]
        if cls == "emergente":
            emerging.append(topic_entry)
        elif cls == "vacio_nicho":
            gaps.append(topic_entry)
        else:
            consolidated.append(topic_entry)

    # Si no se clasificó ningún emergente pero hay tópicos con velocidad > 1.15, promover el más dinámico
    if not emerging and consolidated:
        consolidated.sort(key=lambda x: x["velocity"], reverse=True)
        if consolidated[0]["velocity"] >= 1.1:
            best = consolidated.pop(0)
            best["classification"] = "emergente"
            best["badge_label"] = "🚀 Frontera Dinámica"
            emerging.append(best)

    # Búsqueda balanceada de autores: Tomar el tema consolidado principal (núcleo) Y el tema emergente (frontera)
    target_topics_for_authors = []
    if consolidated:
        target_topics_for_authors.append(consolidated[0])
    if emerging:
        target_topics_for_authors.append(emerging[0])
    if gaps and len(target_topics_for_authors) < 2:
        target_topics_for_authors.append(gaps[0])
    if not target_topics_for_authors:
        target_topics_for_authors = (consolidated + emerging + gaps)[:2]

    # 1. Recuperar Comunidad Editorial Activa de la propia revista (autores recientes con ORCID)
    src_id = source.get("id")
    if src_id:
        comm_auts = get_journal_community_authors(src_id, limit=2, mailto=mailto)
        for ca in comm_auts:
            if ca["orcid"] not in reviewers_map:
                reviewers_map[ca["orcid"]] = ca

    # 2. Recuperar Especialistas Temáticos de Frontera (Sur Global / Iberoamérica)
    for top in target_topics_for_authors:
        auts = get_verified_orcid_authors(
            top["topic_id"],
            limit=authors_per_topic,
            allowed_domains=allowed_domains,
            allowed_fields=allowed_fields,
            mailto=mailto,
        )
        for a in auts:
            if a["orcid"] not in reviewers_map:
                reviewers_map[a["orcid"]] = {
                    **a,
                    "specialty_topic": top["name"],
                    "specialty_topic_id": top["topic_id"],
                }

    suggested_reviewers = list(reviewers_map.values())[:6]

    return {
        "found": True,
        "query": query_or_issn,
        "journal_title": journal_title,
        "issn": issn_val,
        "total_works": source.get("works_count", 0),
        "total_citations": source.get("cited_by_count", 0),
        "consolidated_topics": consolidated,
        "emerging_topics": emerging,
        "gap_topics": gaps,
        "suggested_reviewers": suggested_reviewers,
    }
