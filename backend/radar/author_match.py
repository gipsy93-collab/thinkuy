"""Motor de Match Científico de Thinkuy.

Proporciona dos modalidades deterministas y basadas en evidencia:
1. Match de Revista / CFPs (`find_journal_matches`):
   Evalúa el encaje temático y metodológico de una propuesta con las llamadas a artículos
   (CFPs vigentes) y las líneas editoriales activas de las revistas del campo.
2. Match de Revisores / Editores (`find_reviewer_matches`):
   Identifica evaluadores y editores pares idóneos en el nicho temático exacto,
   aplicando filtros estrictos de exclusión de conflicto de interés (coautores y autoría propia).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from . import db, profile
from . import network as net
from .conversation import STOP
from .normalize import norm

ACADEMIC_STOP = STOP | {
    # Genéricos de investigación y meta-ciencia (ES, PT, EN)
    "estudio", "estudios", "analisis", "articulo", "articulos", "investigacion", "investigaciones",
    "resultados", "resultado", "metodologia", "metodologias", "metodologico", "metodologica",
    "metodologicos", "metodologicas", "metodo", "metodos", "objetivo", "objetivos",
    "conclusion", "conclusiones", "datos", "dato", "autores", "autor", "trabajo", "trabajos",
    "presenta", "presentan", "plantea", "plantean", "muestra", "muestran",
    "aplicacion", "aplicaciones", "aplicado", "aplicada", "aplicados", "aplicadas",
    "institucion", "instituciones", "institucional", "institucionales",
    "estimacion", "estimaciones", "evaluacion", "evaluaciones", "propuesta", "propuestas",
    "enfoque", "enfoques", "perspectiva", "perspectivas", "contexto", "contextos",
    "proceso", "procesos", "desarrollo", "desarrollos", "impacto", "impactos",
    "efecto", "efectos", "relacion", "relaciones", "nivel", "niveles",
    "nacional", "nacionales", "internacional", "internacionales",
    "caso", "casos", "uso", "usos", "utilizacion", "utilizaciones",
    "revision", "revisiones", "general", "generales", "principal", "principales",
    "diferentes", "diversos", "diversas", "mayor", "menor", "alto", "alta", "altos", "altas",
    "bajo", "baja", "bajos", "bajas", "conteo", "conteos",
    "study", "studies", "analysis", "analyses", "paper", "papers", "research", "results",
    "methodology", "methodologies", "methodological", "method", "methods", "objective", "objectives",
    "conclusion", "conclusions", "data", "author", "authors", "work", "works",
    "presents", "approaches", "approach", "review", "literature", "output", "systematic",
    "field", "fields", "growing", "application", "applications", "applied",
    "institution", "institutions", "institutional", "estimation", "estimations",
    "evaluation", "evaluations", "proposal", "proposals", "perspective", "perspectives",
    "context", "contexts", "process", "processes", "development", "developments",
    "impact", "impacts", "effect", "effects", "relation", "relations", "relationship",
    "national", "international", "case", "cases", "use", "uses", "usage", "using", "used",
    "count", "counting",
    "estudo", "estudos", "artigo", "artigos", "pesquisa", "pesquisas", "dados",
    "autores", "trabalho", "trabalhos", "apresenta", "aplicacao", "aplicacoes",
    "metodo", "metodos", "institucional", "institucionais",
    "first", "second", "third", "based", "which", "their", "there",
    "about", "into", "also", "more", "most", "some", "such", "only", "other", "both",
    "toward", "towards", "between", "through", "within", "without", "across",
    "una", "uno", "unos", "unas", "del", "las", "los", "por", "con", "para", "sobre",
}


def _boost_terms() -> set[str]:
    """Términos de impulso del perfil activo."""
    return set(profile.field_profile.author_boost_terms or [])


def _fallback_tokens() -> set[str]:
    """Tokens de respaldo del perfil activo."""
    # Sin términos de fábrica: si el perfil no declara tokens de respaldo, no hay ninguno.
    # (Antes devolvía {comunicacion, medios, tecnologia, periodismo}, lo que sesgaba la
    # coincidencia de autores hacia el campo de prueba.)
    return set(profile.field_profile.author_fallback_tokens or [])


def _clean_tokens(art: dict) -> set[str]:
    kws = " ".join(
        k if isinstance(k, str) else str(k.get("k") or k.get("display_name") or "")
        for k in (art.get("keywords") or [])
    )
    text = f"{art.get('title') or ''} {kws} {art.get('abstract') or ''}"
    return {t for t in norm(text).split() if len(t) > 2 and t not in ACADEMIC_STOP}


def _clean_text_tokens(text: str) -> set[str]:
    return {t for t in norm(text).split() if len(t) > 2 and t not in ACADEMIC_STOP}


def list_anchor_articles(conn: sqlite3.Connection, anchors: list | None = None) -> list[dict]:
    """Lista los artículos del corpus de referencia con autores formateados."""
    anchor_articles = db.load_anchor_articles(conn, anchors)
    field_label = profile.field_profile.field_label
    out = []
    for a in anchor_articles:
        aus = [f"{au.get('given','')} {au.get('family','')}".strip()
               for au in (a.get("authors") or []) if isinstance(au, dict)]
        out.append({
            "id": a["id"],
            "title": a["title"],
            "year": a.get("year"),
            "pub_date": a.get("pub_date"),
            "doi": a.get("doi"),
            "authors": aus,
            "authors_str": ", ".join(aus) if aus else f"Corpus de {field_label}",
            "journal": a.get("journal_title") or field_label,
        })
    return out


# ==============================================================================
# 1. MATCH DE REVISTAS & CALL FOR PAPERS (DÓNDE PUBLICAR)
# ==============================================================================

def find_journal_matches(
    conn: sqlite3.Connection,
    article_id: int | None = None,
    topic_query: str | None = None,
    limit: int = 6
) -> dict:
    """Calcula la fidelidad temática con revistas del campo y CFPs monográficos activos."""
    field_label = profile.field_profile.field_label
    target_art = None
    target_tokens: set[str] = set()
    source_label = ""

    if article_id:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if row:
            target_art = db._row_to_article(row)
            target_tokens = _clean_tokens(target_art)
            source_label = target_art.get("title", "")
    elif topic_query:
        target_tokens = _clean_text_tokens(topic_query)
        source_label = f"Propuesta: {topic_query}"

    if not target_tokens:
        target_tokens = _fallback_tokens()
        source_label = f"Líneas editoriales en {field_label}"

    # Recuperar información del catálogo de revistas registradas
    db_journals = {}
    for row in conn.execute("SELECT id, title, issn_print, issn_online, country FROM journals").fetchall():
        db_journals[norm(row["title"])] = {
            "id": row["id"],
            "title": row["title"],
            "issn_print": row["issn_print"],
            "issn_online": row["issn_online"],
            "country": row["country"],
        }

    # 1. Evaluar CFPs vigentes del perfil
    cfps_matches = []
    cfps = profile.field_profile.cfps or []
    current_year = datetime.now().year

    for cfp in cfps:
        cfp_title = cfp.get("title") or ""
        cfp_desc = cfp.get("description") or ""
        cfp_kws = " ".join(cfp.get("keywords") or [])
        cfp_tokens = _clean_text_tokens(f"{cfp_title} {cfp_desc} {cfp_kws}")
        common = target_tokens & cfp_tokens
        if not common:
            continue

        coverage = len(common) / max(1, len(target_tokens))
        base_score = len(common) * 15
        for special_term in _boost_terms():
            if special_term in common:
                base_score += 15

        j_title = cfp.get("journal") or cfp.get("journal_title") or field_label
        j_meta = db_journals.get(norm(j_title), {})
        contact_pts = [t.capitalize() for t in list(common)[:5]]
        fidelity = min(98, max(65, int(60 + coverage * 35 + min(20, base_score))))

        deadline = cfp.get("deadline") or "Convocatoria abierta"
        cfps_matches.append({
            "id": f"cfp-{norm(cfp_title)[:25]}",
            "journal": j_title,
            "issn": j_meta.get("issn_online") or j_meta.get("issn_print"),
            "country": j_meta.get("country") or cfp.get("country"),
            "match_type": "cfp",
            "cfp_title": cfp_title,
            "cfp_deadline": deadline,
            "fidelity": fidelity,
            "shared_concepts": contact_pts,
            "sample_articles": [],
            "rationale": (
                f"Convocatoria activa: «{cfp_title}» (Límite: {deadline}). "
                f"Fuerte alineación con los descriptores: {', '.join(contact_pts[:3])}."
            ),
            "url": cfp.get("url"),
            "raw_score": base_score + 50,  # Prioridad alta para CFPs vigentes
        })

    # 2. Evaluar Producción y Línea Editorial de las Revistas del Catálogo
    journal_articles: dict[str, list[dict]] = {}
    rows = conn.execute(
        "SELECT * FROM articles WHERE journal_title IS NOT NULL AND journal_title != '' ORDER BY pub_date DESC LIMIT 3000"
    ).fetchall()

    for r in rows:
        art = db._row_to_article(r)
        jt = (art.get("journal_title") or "").strip()
        if not jt:
            continue
        journal_articles.setdefault(jt, []).append(art)

    journal_matches = []
    total_query_tokens_count = max(1, len(target_tokens))

    for jt, arts in journal_articles.items():
        jt_norm = norm(jt)
        j_meta = db_journals.get(jt_norm, {})

        matched_arts = []
        journal_shared_tokens: set[str] = set()

        for art in arts:
            art_tokens = _clean_tokens(art)
            common = target_tokens & art_tokens
            if common:
                journal_shared_tokens.update(common)
                matched_arts.append({
                    "art": art,
                    "common_count": len(common),
                    "year": art.get("year") or 0,
                })

        if not matched_arts:
            continue

        # Ordenar artículos afines por solapamiento y año
        matched_arts.sort(key=lambda x: (-x["common_count"], -x["year"]))
        relevant_count = len(matched_arts)
        recent_count = sum(1 for a in matched_arts if (a["year"] or 0) >= (current_year - 2))

        # Cobertura léxica real del query
        coverage_ratio = len(journal_shared_tokens) / total_query_tokens_count
        
        # Puntuación determinista de fidelidad
        raw_score = (len(journal_shared_tokens) * 12) + (relevant_count * 4) + (recent_count * 4)
        for special_term in _boost_terms():
            if special_term in journal_shared_tokens:
                raw_score += 15

        # Fidelidad basada en cobertura real y densidad
        fidelity = min(98, max(45, int(40 + coverage_ratio * 45 + min(15, relevant_count * 2))))
        contact_pts = [t.capitalize() for t in list(journal_shared_tokens)[:5]]

        sample_list = []
        for item in matched_arts[:2]:
            a = item["art"]
            sample_list.append({
                "title": a.get("title"),
                "year": a.get("year"),
                "doi": a.get("doi"),
                "journal": jt,
            })

        journal_matches.append({
            "id": f"journal-{jt_norm[:25]}",
            "journal": jt,
            "issn": j_meta.get("issn_online") or j_meta.get("issn_print") or (arts[0].get("issn") if arts else None),
            "country": j_meta.get("country"),
            "match_type": "editorial_line",
            "cfp_title": None,
            "cfp_deadline": None,
            "fidelity": fidelity,
            "shared_concepts": contact_pts,
            "sample_articles": sample_list,
            "rationale": (
                f"Línea editorial regular con publicaciones en {', '.join(contact_pts[:3])}. "
                f"Registra {relevant_count} artículo(s) afines en el catálogo."
            ),
            "url": None,
            "raw_score": raw_score,
            "coverage_ratio": coverage_ratio,
        })

    # Combinar CFPs y revistas, ordenando por cobertura y relevancia
    all_results = sorted(cfps_matches + journal_matches, key=lambda x: -x["raw_score"])

    # Evitar duplicar la misma revista si ya tiene un CFP mejor rankeado
    seen_journals = set()
    deduped = []
    for item in all_results:
        j_key = norm(item["journal"])
        if j_key in seen_journals and item["match_type"] == "editorial_line":
            continue
        seen_journals.add(j_key)
        deduped.append(item)
        if len(deduped) >= limit:
            break

    return {
        "status": "ok",
        "source": {
            "label": source_label,
            "tokens": list(target_tokens)[:8],
        },
        "count": len(deduped),
        "matches": deduped,
    }


# ==============================================================================
# 2. MATCH DE REVISORES / EDITORES (PARES EVALUADORES SIN CONFLICTO)
# ==============================================================================

def find_reviewer_matches(
    conn: sqlite3.Connection,
    article_id: int | None = None,
    author_name: str | None = None,
    topic_query: str | None = None,
    limit: int = 6
) -> dict:
    """Identifica evaluadores y editores pares con especialidad comprobada y sin conflicto de interés."""
    field_label = profile.field_profile.field_label
    target_art = None
    target_tokens: set[str] = set()
    source_label = ""
    author_source_name = author_name or ""

    if article_id:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if row:
            target_art = db._row_to_article(row)
            target_tokens.update(_clean_tokens(target_art))
            source_label = target_art.get("title", "")
            if not author_source_name and target_art.get("authors"):
                aus = [f"{au.get('given','')} {au.get('family','')}".strip()
                       for au in target_art.get("authors") if isinstance(au, dict)]
                author_source_name = ", ".join(aus[:2])

    if topic_query:
        target_tokens.update(_clean_text_tokens(topic_query))
        if not source_label:
            source_label = f"Línea de evaluación: {topic_query}"

    if author_name:
        rows = conn.execute(
            "SELECT * FROM articles WHERE authors LIKE ? ORDER BY pub_date DESC LIMIT 5",
            (f"%{author_name}%",)
        ).fetchall()
        for r in rows:
            target_tokens.update(_clean_tokens(db._row_to_article(r)))
        if not source_label:
            source_label = f"Manuscrito de {author_name}"

    if not target_tokens:
        target_tokens = _fallback_tokens()
        source_label = f"Especialistas en {field_label}"

    # Recuperar todos los artículos para resolución de identidades y grafo de coautoría
    rows = conn.execute(
        "SELECT * FROM articles ORDER BY pub_date DESC LIMIT 2000"
    ).fetchall()
    all_arts = [db._row_to_article(r) for r in rows]

    # Mapa de identidades canónicas
    identity_map = net.author_identity_map(([target_art] if target_art else []) + all_arts)

    # 1. Identificar autores del manuscrito y su red directa de coautoría (CONFLICTO DE INTERÉS)
    target_author_ids: set[str] = set()
    coauthor_conflict_ids: set[str] = set()
    target_author_names_norm: set[str] = set()

    if target_art:
        for au in target_art.get("authors") or []:
            if isinstance(au, dict):
                cid = net.canonical_author_id(au, identity_map)
                if cid:
                    target_author_ids.add(cid)
                g, f = net.clean_author_name(str(au.get("given") or ""), str(au.get("family") or ""))
                if f"{g} {f}".strip():
                    target_author_names_norm.add(norm(f"{g} {f}"))
    if author_source_name:
        target_author_names_norm.add(norm(author_source_name))
        direct_orcid = net.normalize_orcid(author_source_name)
        if direct_orcid:
            target_author_ids.add(f"orcid:{direct_orcid}")

    # Asociar IDs canónicos a partir de los nombres normalizados del autor
    target_has_orcids = any(tid.startswith("orcid:") for tid in target_author_ids)
    for art in all_arts:
        for au in (art.get("authors") or []):
            if isinstance(au, dict):
                g, f = net.clean_author_name(str(au.get("given") or ""), str(au.get("family") or ""))
                if norm(f"{g} {f}") in target_author_names_norm:
                    cid = net.canonical_author_id(au, identity_map)
                    au_orcid = net.normalize_orcid(au.get("orcid"))
                    if au_orcid:
                        if target_has_orcids:
                            if f"orcid:{au_orcid}" in target_author_ids and cid:
                                target_author_ids.add(cid)
                        else:
                            # El target no especificó ORCID previo; adoptar el ORCID de este autor
                            if cid:
                                target_author_ids.add(cid)
                    else:
                        if cid:
                            target_author_ids.add(cid)

    # Buscar en todos los artículos coautorías de los autores target
    for art in all_arts:
        art_authors = [au for au in (art.get("authors") or []) if isinstance(au, dict)]
        art_cids = {net.canonical_author_id(au, identity_map) for au in art_authors}
        art_cids.discard(None)

        # Si el artículo incluye a algún autor del target, todos los coautores del paper son conflicto
        if art_cids & target_author_ids:
            coauthor_conflict_ids.update(art_cids)

    # Todos los autores target son conflicto
    coauthor_conflict_ids.update(target_author_ids)

    # 2. Evaluar candidatos a revisor par
    current_year = datetime.now().year
    reviewer_candidates: dict[str, dict] = {}

    for art in all_arts:
        # Si el artículo fue escrito por el autor objetivo, omitirlo
        art_authors = [au for au in (art.get("authors") or []) if isinstance(au, dict)]
        art_cids = {net.canonical_author_id(au, identity_map) for au in art_authors}
        if art_cids & target_author_ids:
            continue

        art_tokens = _clean_tokens(art)
        common = target_tokens & art_tokens
        if not common:
            continue

        art_year = art.get("year") or 0
        is_recent = art_year >= (current_year - 2)

        base_work_score = len(common) * 5 + (8 if is_recent else 0)
        for special_term in _boost_terms():
            if special_term in common:
                base_work_score += 10

        for au in art_authors:
            key = net.canonical_author_id(au, identity_map)
            g, f = net.clean_author_name(str(au.get("given") or ""), str(au.get("family") or ""))
            name = f"{g} {f}".strip()
            name_n = norm(name)

            if not key or not name or len(name) < 4:
                continue

            # FILTRO ESTRICTO DE CONFLICTO DE INTERÉS
            if key in coauthor_conflict_ids:
                continue
            # Solo verificar por nombre si el candidato no tiene ORCID propio verificado
            if not key.startswith("orcid:") and name_n in target_author_names_norm:
                continue

            if key not in reviewer_candidates:
                reviewer_candidates[key] = {
                    "id": key,
                    "name": name,
                    "orcid": key[6:] if key.startswith("orcid:") else None,
                    "raw_score": 0,
                    "primary_journal": art.get("journal_title") or field_label,
                    "articles": [],
                    "common_tokens": set(),
                    "recent_count": 0,
                    "total_matches": 0,
                }

            cand = reviewer_candidates[key]
            if len(name) > len(cand["name"]):
                cand["name"] = name
            direct_orcid = net.normalize_orcid(au.get("orcid"))
            if direct_orcid and not cand["orcid"]:
                cand["orcid"] = direct_orcid

            cand["raw_score"] += base_work_score
            cand["common_tokens"].update(common)
            cand["total_matches"] += 1
            if is_recent:
                cand["recent_count"] += 1

            if len(cand["articles"]) < 2:
                cand["articles"].append({
                    "title": art.get("title"),
                    "year": art.get("year"),
                    "journal": art.get("journal_title") or field_label,
                    "doi": art.get("doi"),
                })

    total_query_tokens_count = max(1, len(target_tokens))
    sorted_reviewers = sorted(reviewer_candidates.values(), key=lambda x: -x["raw_score"])
    matches = []

    for c in sorted_reviewers[:limit]:
        coverage_ratio = len(c["common_tokens"]) / total_query_tokens_count
        # Idoneidad editorial real
        idoneity = min(98, max(50, int(45 + coverage_ratio * 40 + min(15, c["total_matches"] * 3))))
        contact_pts = [t.capitalize() for t in list(c["common_tokens"])[:5]]
        pts_str = ", ".join(contact_pts[:3])

        # Generar ficha de justificación para OJS / Comité Editorial
        arts_summary = "\n".join(
            f"  • {a['title']} ({a.get('year', 's.f.')}, {a.get('journal', '')}) "
            f"{'https://doi.org/' + a['doi'] if a.get('doi') else ''}"
            for a in c["articles"]
        )

        ojs_slip = (
            f"EVALUADOR/A SUGERIDO/A:\n"
            f"Nombre: {c['name']}\n"
            f"ORCID: {c.get('orcid') or 'No registrado'}\n"
            f"Especialidad verificada: {pts_str}\n"
            f"Publicaciones afines:\n{arts_summary}\n"
            f"Control de conflicto de interés: Sin coautorías registradas con el autor principal."
        )

        matches.append({
            "id": c["id"],
            "name": c["name"],
            "orcid": c.get("orcid"),
            "idoneity": idoneity,
            "affinity": idoneity,  # Compatibilidad retroactiva
            "journal": c["primary_journal"],
            "conflict_status": "Sin conflicto de interés detectado",
            "shared_concepts": contact_pts,
            "articles": c["articles"],
            "recent_count": c["recent_count"],
            "total_matches": c["total_matches"],
            "rationale": (
                f"Especialista activo en {pts_str}. "
                f"Registra {c['total_matches']} publicación(es) afines ({c['recent_count']} recientes). "
                f"Sin coautorías previas detectadas con el autor."
            ),
            "ojs_slip": ojs_slip,
        })

    return {
        "status": "ok",
        "source": {
            "label": source_label,
            "author": author_source_name,
            "tokens": list(target_tokens)[:8],
        },
        "count": len(matches),
        "matches": matches,
    }


# Compatibilidad retroactiva
def find_author_matches(
    conn: sqlite3.Connection,
    article_id: int | None = None,
    author_name: str | None = None,
    topic_query: str | None = None,
    limit: int = 6
) -> dict:
    """Función de compatibilidad que redirige a la búsqueda de revisores."""
    return find_reviewer_matches(
        conn,
        article_id=article_id,
        author_name=author_name,
        topic_query=topic_query,
        limit=limit
    )

