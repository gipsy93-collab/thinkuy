"""Subrouter de la API de Thinkuy."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Body, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from ... import config, db, profile
from ..common import (
    _as_int,
    _as_list,
    _date_int,
    _field_profile,
    _http,
    _query_articles,
    _safe_doi,
    _widget_card,
    _with_display_keywords,
)
from ... import librarian, socratic, topics
from ...conversation import score_article, why_labels
from ...harvester import live_search
from ...matching import parse_keywords, rank_articles

router = APIRouter(tags=['librarian'])
log = logging.getLogger('radar.api.librarian')
PROFILE = profile.field_profile

@router.post("/api/socratic/analyze")
def socratic_analyze(payload: dict = Body(...)):
    """Inicia el diálogo socrático a partir de la indagación o tema del usuario."""
    inquiry = str(payload.get("inquiry") or "").strip()
    if not inquiry:
        raise HTTPException(422, "inquiry es obligatorio")
    conn = db.connect()
    try:
        return socratic.analyze_inquiry(inquiry, conn)
    finally:
        conn.close()


@router.post("/api/socratic/concert")
def socratic_concert(payload: dict = Body(...)):
    """Concierta el horizonte de radar temático y opcionalmente lo ancla."""
    # Compat: backend espera field_id/inquiry/reflection; PWA manda
    # field_name/original_inquiry/user_reflection. Aceptamos ambos.
    field_id = str(payload.get("field_id") or payload.get("field_name") or "").strip()
    inquiry = str(payload.get("inquiry") or payload.get("original_inquiry") or "").strip()
    reflection = str(payload.get("reflection") or payload.get("user_reflection") or "").strip()
    pin = bool(payload.get("pin", False))
    # Si viene nombre en vez de id, resolver a id real del perfil
    if field_id and "/" not in field_id and " " in field_id:
        try:
            for f in topics.fields():
                if f.get("name") == field_id or f.get("id") == field_id:
                    field_id = f["id"]
                    break
        except Exception:
            pass
    conn = db.connect()
    try:
        res = socratic.concert_radar(field_id, inquiry, reflection, conn)
        if pin and res.get("recommended_keywords"):
            w = db.watch_create(conn, res["recommended_keywords"], res["label"])
            res["pin"] = w
        return res
    finally:
        conn.close()


@router.post("/api/librarian/assist")
def librarian_assist(payload: dict = Body(...)):
    """El bibliotecario de referencia de Thinkuy:
    1. Escucha la indagación en lenguaje natural (con typos y abreviaturas).
    2. Modela la escucha: 'Ah, lo que usted busca es...' + campo + keywords.
    3. Activa el catálogo del radar y recupera los artículos más relevantes.
    4. Explica en lenguaje natural los hallazgos encontrados en el catálogo.
    """
    inquiry = str(payload.get("inquiry") or "").strip()
    if not inquiry:
        raise HTTPException(422, "inquiry es obligatorio")
    limit = _as_int(payload.get("limit"), default=50, minimum=1, maximum=150)

    from ... import librarian

    all_fields = topics.fields()
    has_delimiters = bool(re.search(r'[,;"\n]', inquiry))

    # Palabras de parada GENÉRICAS del acto de preguntar (andamiaje de la consulta). Los
    # términos omnipresentes de una disciplina concreta NO van aquí: los declara el perfil
    # activo en `ubiquitous_terms`, para que el modo neutro no descarte palabras de nadie.
    domain_stopwords = {
        "busco", "busca", "sobre", "para", "como", "esta", "este", "entre", "desde",
        "hacia", "articulos", "articulo", "informacion", "investigacion", "estudios",
        "estudio", "quiero", "saber", "acerca", "donde", "cual", "cuales", "todo",
        "todas", "todos", "unas", "unos", "otra", "otro", "otras", "otros",
        "col", "esp", "investigaciones", "trabajos", "trabajo", "investigo",
    }
    domain_stopwords |= {str(t).strip().lower() for t in (PROFILE.ubiquitous_terms or []) if str(t).strip()}

    # 1. Escuchar e interpretar / Parsing de palabras clave
    campo_neutro = {"id": PROFILE.id, "name": PROFILE.name,
                    "description": "Búsqueda sin filtro de disciplina."}
    if has_delimiters:
        # Consulta por palabras clave explícitas
        kw_parsed = parse_keywords(inquiry)
        corrected = ", ".join(kw_parsed)
        field_obj = all_fields[0] if all_fields else campo_neutro
        field_id = field_obj.get("id") or PROFILE.id
        heard_as = f"Búsqueda por descriptores: {corrected}"
        listen_mode = "deterministic_keywords"
        query_keywords = kw_parsed
        fuera_del_campo = False
    else:
        # Lenguaje natural -> Bibliotecario
        heard_res = librarian.listen(inquiry, all_fields)
        corrected = heard_res.get("corrected") or inquiry
        field_id = heard_res.get("field_id") or (all_fields[0].get("id") if all_fields else PROFILE.id)
        heard_as = heard_res.get("heard_as") or f"Ah, lo que usted busca es {corrected}"
        listen_mode = heard_res.get("mode", "deterministic")
        # Salida de campo: la consulta no pertenece al campo activo. Se declara en lugar de
        # disfrazarla con el tema más parecido del perfil (la garantía anti-monotemática).
        fuera_del_campo = str(field_id).strip().lower() == "ninguno"
        if fuera_del_campo:
            field_obj = campo_neutro
            heard_as = f"{heard_as} (fuera del campo activo: se busca sin clasificar)"
        else:
            field_obj = next((f for f in all_fields if f.get("id") == field_id),
                             all_fields[0] if all_fields else campo_neutro)

        compound_kws = heard_res.get("compound_keywords") or []
        if compound_kws:
            query_keywords = [k for k in compound_kws if k.lower().strip() not in domain_stopwords]
        else:
            chunks = [c.strip() for c in re.split(r'\b(?:en|de|del|sobre|para|con|por|hacia|desde|em|com)\b', corrected, flags=re.IGNORECASE) if c.strip() and len(c.strip()) > 2]
            query_keywords = [c for c in chunks if c.lower().strip() not in domain_stopwords]

        if not query_keywords:
            query_keywords = [corrected]

    conn = db.connect()
    try:
        requested_source = str(payload.get("source") or "live").strip().lower()
        data_source = "live_probe"
        probe_engine = "Sonda Federada: OpenAlex · OpenAIRE · Dialnet"
        all_matched = []
        matched_articles = []
        ecosystem_data = {}
        saturation_data = {}
        top_authors = []
        suggested_kws = []

        # POR DEFECTO: Consultar directamente las bases de datos externas en tiempo real (Sonda Federada)
        # NUNCA usar el catálogo local a menos que el usuario lo solicite expresamente con source="local"
        diagnostico_sonda: dict = {}
        if requested_source != "local":
            try:
                from ...harvester import live_probe
                probe_res = live_probe.probe_topic(
                    query=corrected,
                    compound_keywords=query_keywords,
                    limit=max(limit, 60),
                )
                if probe_res:
                    diagnostico_sonda = {
                        "consulta_usada": probe_res.get("consulta_usada"),
                        "relajada": bool(probe_res.get("relajada")),
                        "intentos": probe_res.get("intentos") or [],
                    }
                if probe_res and probe_res.get("articles"):
                    data_source = "live_probe"
                    probe_engine = probe_res.get("probe_engine", "Sonda Federada: OpenAlex · OpenAIRE · Dialnet")
                    all_matched = probe_res["articles"]
                    matched_articles = all_matched
                    ecosystem_data = probe_res["ecosystem"]
                    saturation_data = probe_res["saturation"]
                    top_authors = probe_res["top_authors"]
                    suggested_kws = probe_res.get("suggested_keywords") or []
                    _with_display_keywords(matched_articles, candidate_terms=query_keywords, limit=4)
                    # Indexar la búsqueda en el catálogo es OPCIONAL y por defecto está APAGADO:
                    # buscar es una lectura y no debe ensanchar un estado compartido. Lo que sí
                    # persiste es transferir resultados a una revisión (acción explícita).
                    if config.INDEX_LIVE_RESULTS:
                        for art in all_matched:
                            try:
                                _, art_id = db.upsert_article(conn, art)
                                art["id"] = art_id
                            except Exception as e:
                                log.debug("Error al indexar obra de sonda viva en sesión: %s", e)
            except Exception as e:
                log.warning("Fallo al ejecutar sonda en vivo federada: %s", e)

        # Si el usuario solicitó explícitamente su catálogo local ("local"):
        if not all_matched and requested_source == "local":
            data_source = "catalog"
            arts = _query_articles(conn, days=None, langs=[], sources=[], max_rows=None, keywords=query_keywords or [])
            ranked = rank_articles(arts, query_keywords)
            primary_kw = query_keywords[0] if query_keywords else ""
            if len(primary_kw.split()) >= 2:
                all_matched = [
                    a for a in ranked
                    if any(m.get("keyword") == primary_kw for m in a.get("matched", []))
                ]
            else:
                all_matched = [a for a in ranked if a.get("match_score", 0) > 0]
        elif not all_matched and data_source == "live_probe":
            ecosystem_data = {
                "total_matched": 0,
                "sources": {"openalex": 0},
                "top_journals": [],
                "top_authors": [],
                "years": {"min": None, "max": None, "recent_count": 0},
            }
            saturation_data = {
                "level": "uncovered",
                "label": "Sin registros en tiempo real",
                "description": (
                    "No se localizaron publicaciones en acceso abierto para esta consulta. "
                    + (f"Se probaron {len(diagnostico_sonda.get('intentos') or [])} formulaciones, "
                       f"desde la más específica hasta «{diagnostico_sonda.get('intentos', [{}])[-1].get('consulta', '')}». "
                       if diagnostico_sonda.get("intentos") else "")
                    + "Prueba con menos términos o con los descriptores del campo."
                ),
                "review_count": 0,
            }

        if data_source == "catalog":
            matched_articles = all_matched[:limit]
            profile_data = _field_profile(conn)
            for a in matched_articles:
                sig = score_article(a, profile_data)
                a["conversation"] = {**sig, "why": why_labels(sig, "es")}
                a["thematic_fields"] = topics.classify_article_fields(a)
                a.pop("referenced_ids", None)
            _with_display_keywords(matched_articles, candidate_terms=query_keywords, limit=4)

            # Métricas de Ecosistema
            total_matched = len(all_matched)

            # Revistas Núcleo (concentración editorial)
            journal_counts: dict[str, int] = {}
            source_counts: dict[str, int] = {}
            author_data: dict[str, dict] = {}
            years_list: list[int] = []

            for a in all_matched:
                # Revistas
                jname = a.get("journal_title") or a.get("journal") or "Revista no declarada"
                jname = jname.strip()
                if jname:
                    journal_counts[jname] = journal_counts.get(jname, 0) + 1

                # Fuentes
                src = (a.get("source") or "catálogo").lower()
                source_counts[src] = source_counts.get(src, 0) + 1

                # Años
                y_val = a.get("year") or (a.get("pub_date") or "")[:4]
                if y_val and str(y_val).isdigit():
                    years_list.append(int(y_val))

                # Autores
                doi = a.get("doi") or ""
                for auth in (a.get("authors") or []):
                    name = ""
                    if isinstance(auth, dict):
                        name = f"{auth.get('given', '')} {auth.get('family', '')}".strip() or str(auth.get("name") or "")
                    elif isinstance(auth, str):
                        if auth.startswith("{") and "family" in auth:
                            try:
                                item = json.loads(auth.replace("'", '"'))
                                name = f"{item.get('given', '')} {item.get('family', '')}".strip()
                            except Exception:
                                name = auth.strip()
                        else:
                            name = auth.strip()
                    if name and len(name) > 3:
                        if name not in author_data:
                            author_data[name] = {"count": 0, "dois": []}
                        author_data[name]["count"] += 1
                        if doi and doi not in author_data[name]["dois"]:
                            author_data[name]["dois"].append(doi)

            sorted_journals = sorted(journal_counts.items(), key=lambda x: -x[1])
            top_journals = [{"name": name, "count": count} for name, count in sorted_journals[:5]]

            sorted_authors = sorted(author_data.items(), key=lambda x: -x[1]["count"])
            top_authors = [{"name": name, "count": d["count"], "dois": d["dois"][:3]} for name, d in sorted_authors[:6]]

            # Rango temporal
            year_min = min(years_list) if years_list else None
            year_max = max(years_list) if years_list else None
            recent_cutoff = date.today().year - 3
            recent_count = sum(1 for y in years_list if y >= recent_cutoff)

            # Diagnóstico de Saturación / Brechas Epistémicas
            review_count = sum(1 for a in all_matched if any(t in (a.get("title") or "").lower() for t in ("revisión", "revision", "scoping", "síntesis", "sintesis", "sistemática", "review")))
            if total_matched == 0:
                sat_level = "uncovered"
                sat_label = "Vacío Absoluto en el Catálogo"
                sat_desc = "No se registran documentos directamente indexados con estos términos exactos en el acervo actual."
            elif total_matched <= 6:
                sat_level = "niche"
                sat_label = "Nicho Fértil / Vacío de Investigación"
                sat_desc = f"Baja densidad bibliográfica ({total_matched} publicaciones). Constituye un frente de investigación abierto y fértil para tesis o proyectos sin saturación de literatura."
            elif total_matched <= 25:
                sat_level = "emerging"
                sat_label = "Conversación en Consolidación"
                sat_desc = f"Masa crítica emergente ({total_matched} publicaciones). Cuenta con antecedentes sólidos y espacio para aportes metodológicos o empíricos."
            else:
                sat_level = "saturated"
                sat_label = "Campo Altamente Denso / Maduro"
                sat_desc = f"Alta densidad bibliográfica ({total_matched} publicaciones). Requiere formulaciones conceptuales específicas para diferenciarse del corpus consolidado."

            if review_count == 0 and total_matched >= 8:
                sat_desc += " [Oportunidad detectada: Ausencia de artículos de síntesis o revisión sistemática]."

            saturation_data = {
                "level": sat_level,
                "label": sat_label,
                "description": sat_desc,
                "review_count": review_count,
            }

            ecosystem_data = {
                "total_matched": total_matched,
                "sources": source_counts,
                "top_journals": top_journals,
                "years": {
                    "min": year_min,
                    "max": year_max,
                    "recent_count": recent_count,
                },
            }

            # Descriptores relacionados para refinamiento con un clic
            related_kws: dict[str, int] = {}
            for a in all_matched[:35]:
                for kw in (a.get("keywords") or []):
                    k = kw.strip() if isinstance(kw, str) else ""
                    if k and len(k) > 3 and k.lower() not in [q.lower() for q in query_keywords]:
                        related_kws[k] = related_kws.get(k, 0) + 1
            sorted_related = sorted(related_kws.items(), key=lambda x: -x[1])
            suggested_kws = [k for k, _ in sorted_related[:8]]

        # 3. El Auditor de Ecosistemas Científicos explica los hallazgos.
        # Si la consulta se amplió, la explicación debe referirse a la consulta REALMENTE usada:
        # citar los descriptores originales cuando no fueron los que trajeron los resultados
        # confunde al investigador (y ya se avisa aparte, antes de la explicación).
        keywords_explicados = ([diagnostico_sonda["consulta_usada"]]
                               if diagnostico_sonda.get("relajada") and diagnostico_sonda.get("consulta_usada")
                               else query_keywords)
        explanation = librarian.explain_results(
            inquiry=inquiry,
            heard_as=heard_as,
            articles=matched_articles,
            field=field_obj,
            keywords=keywords_explicados,
            ecosystem=ecosystem_data,
            saturation=saturation_data,
            data_source=data_source,
        )

        # Si hubo que ampliar la consulta para encontrar algo, se dice ANTES de la explicación:
        # el investigador debe saber que los resultados no provienen de su formulación literal.
        if diagnostico_sonda.get("relajada") and diagnostico_sonda.get("consulta_usada"):
            explanation = (
                f"Su consulta completa no arrojó resultados, así que la búsqueda se amplió a "
                f"«{diagnostico_sonda['consulta_usada']}». Estos son los trabajos que aparecen "
                f"con esos descriptores. " + (explanation or "")
            )

        return {
            "inquiry": inquiry,
            "corrected": corrected,
            "heard_as": heard_as,
            "field": {
                "id": field_obj.get("id"),
                "name": field_obj.get("name"),
                "description": field_obj.get("description"),
            },
            "keywords": query_keywords[:6],
            "listen_mode": listen_mode,
            "data_source": data_source,
            "probe_engine": probe_engine,
            "explanation": explanation,
            "ecosystem": ecosystem_data,
            "saturation": saturation_data,
            "top_authors": top_authors,
            "suggested_keywords": suggested_kws,
            "total_matches": len(matched_articles),
            "fuera_del_campo": fuera_del_campo,
            "consulta_usada": diagnostico_sonda.get("consulta_usada"),
            "consulta_relajada": diagnostico_sonda.get("relajada", False),
            "consultas_intentadas": diagnostico_sonda.get("intentos") or [],
            "articles": matched_articles,
        }
    finally:
        conn.close()

