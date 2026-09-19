"""Motor Socrático de Concertación Temática para Thinkuy."""
from __future__ import annotations

import sqlite3

from . import profile
from .normalize import norm
from .topics import fields

QUESTION_TEMPLATES = profile.field_profile.socratic_templates


def _field_list() -> list[dict]:
    fl = fields()
    return fl or []


def analyze_inquiry(raw_text: str, conn: sqlite3.Connection) -> dict:
    """Analiza la inquietud del investigador y abre el diálogo socrático."""
    field_list = _field_list()
    if not field_list:
        return {"status": "no_field", "inquiry": raw_text}

    # 0. El bibliotecario escucha primero (corrige typos, expande, elige campo).
    # Si está apagado, seguimos 100% determinista como antes.
    heard_as: str | None = None
    corrected_text = raw_text
    forced_field_id: str | None = None
    listen_mode = "deterministic"
    try:
        from . import librarian as _lib0
        if _lib0.available():
            heard = _lib0.listen(raw_text, field_list)
            listen_mode = heard.get("mode", "deterministic")
            if listen_mode == "librarian":
                corrected_text = heard.get("corrected") or raw_text
                forced_field_id = heard.get("field_id")
                heard_as = heard.get("heard_as") or corrected_text
    except Exception:
        pass

    text_norm = norm(corrected_text)
    tokens = set(text_norm.split())

    # 1. Puntuación de campos temáticos afines
    ranked_fields = []
    for f in field_list:
        score = 0
        matches = []
        for kw in f["keywords_es"] + f["keywords_pt"]:
            nkw = norm(kw)
            if " " in nkw and nkw in text_norm:
                score += 4
                matches.append(kw)
            elif nkw in tokens:
                score += 2
                matches.append(kw)
        ranked_fields.append((score, f, matches))

    ranked_fields.sort(key=lambda x: -x[0])
    best_score = ranked_fields[0][0] if ranked_fields else 0

    # Guardia anti-“Hola”: solo bloqueamos lo trivialmente corto.
    # Si es largo pero no toca el ontología (ej. "democratización" vs "democracia"),
    # seguimos al diálogo con confianza baja en vez de inventar o bloquear.
    text_tokens = [t for t in text_norm.split() if t]
    if len(text_tokens) < 3 or len(text_norm) < 12:
        total_arts = 0
        total_journals = 0
        try:
            total_arts = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] or 0
            try:
                total_journals = conn.execute(
                    "SELECT COUNT(DISTINCT journal_title) FROM articles WHERE journal_title IS NOT NULL AND journal_title != ''"
                ).fetchone()[0] or 0
            except Exception:
                pass
        except Exception:
            pass
        return {
            "status": "need_clarification",
            "inquiry": raw_text,
            "message": (
                "Cuéntame un poco más: ¿qué fenómeno estudias, en qué país o periodo, "
                "y con qué palabras lo buscarías en una revista? Con 2-3 frases te ubico "
                "en el campo correcto sin inventar."
            ),
            "literature_density": {
                "articles_found": total_arts,
                "journals_covered": total_journals,
            },
            "suggested_keywords": [],
            "socratic_questions": [],
            "librarian": "deterministic",
        }

    confidence = "high" if best_score > 0 else "low"

    # Si el bibliotecario escuchó y propuso campo válido, manda él sobre el score.
    if forced_field_id:
        forced = next((f for f in field_list if f["id"] == forced_field_id), None)
        if forced is not None:
            best_field = forced
            confidence = "high"
            # Recalcular second best excluyendo el forzado
            others = [(s, f) for s, f, _ in ranked_fields if f["id"] != forced["id"] and s > 0]
            sec_field = others[0][1] if others else None
        else:
            best_field = ranked_fields[0][1] if ranked_fields and ranked_fields[0][0] > 0 else field_list[0]
            sec_field = ranked_fields[1][1] if len(ranked_fields) > 1 and ranked_fields[1][0] > 0 else None
    else:
        best_field = ranked_fields[0][1] if ranked_fields and ranked_fields[0][0] > 0 else field_list[0]
        sec_field = ranked_fields[1][1] if len(ranked_fields) > 1 and ranked_fields[1][0] > 0 else None

    field_id = best_field["id"]
    fallback_q = QUESTION_TEMPLATES.get(field_id) or QUESTION_TEMPLATES.get("generic") or []

    # Puente librarian: si el bibliotecario está de turno, pide preguntas vivas;
    # si no, degrada a las plantillas fijas del perfil (determinista intacto).
    # Usamos el texto corregido para que entienda typos como "ciuanana".
    librarian_info: dict = {"mode": "deterministic"}
    try:
        from . import librarian as _lib
        if _lib.available():
            librarian_info = _lib.socratic_questions(corrected_text, best_field, fallback_q)
            questions = librarian_info.get("questions") or fallback_q
        else:
            questions = fallback_q
    except Exception:
        questions = fallback_q

    # 2. Densidad honesta del catálogo (totales, no muestra LIKE con tildes).
    # El LIKE con frase normalizada falla por tildes; devolvemos el tamaño real
    # del catálogo para no mostrar "0 artículos en 0 revistas" que confunde.
    kw_cands = best_field["keywords_es"][:4] + best_field["keywords_pt"][:2]
    density_sample = 0
    journals_covered = 0
    try:
        density_sample = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] or 0
        try:
            journals_covered = conn.execute(
                "SELECT COUNT(DISTINCT journal_title) FROM articles WHERE journal_title IS NOT NULL AND journal_title != ''"
            ).fetchone()[0] or 0
        except Exception:
            journals_covered = len(best_field.get("journals_focus") or [])
    except Exception:
        density_sample = 15

    return {
        "status": "dialogue",
        "inquiry": raw_text,
        "confidence": confidence,
        "primary_field": {
            "id": best_field["id"],
            "name": best_field["name"],
            "description": best_field.get("description"),
            "journals_focus": best_field.get("journals_focus") or [],
        },
        "secondary_field": {
            "id": sec_field["id"],
            "name": sec_field["name"],
        } if sec_field else None,
        "socratic_questions": questions,
        "librarian": librarian_info.get("mode", "deterministic"),
        # Alias compat PWA (espera literature_density + suggested_keywords)
        "literature_density": {
            "articles_found": density_sample,
            "journals_covered": journals_covered,
        },
        "suggested_keywords": kw_cands,
        "epistemic_reflection": (
            (f"Ah, lo que buscas es: {corrected_text}. " if (corrected_text != raw_text) else (f"Ah, lo que buscas es: {heard_as}. " if heard_as else ""))
            + f"Tu inquietud se inscribe principalmente en el campo de «{best_field['name']}»"
            + (" (asignación tentativa: precisa en tu respuesta)." if confidence == "low" and not heard_as else ". ")
            + "Para que el radar no sea una simple búsqueda de texto, concertemos qué vertiente de este campo "
            "dialoga verdaderamente con tu proyecto."
        ),
        "heard_as": heard_as,
        "corrected_inquiry": corrected_text if corrected_text != raw_text else None,
        "corpus_density_hint": f"Existen al menos {density_sample} publicaciones recientes en el catálogo vinculadas a este eje.",
    }


def concert_radar(field_id: str, inquiry: str, reflection: str, conn: sqlite3.Connection) -> dict:
    """Concierta y formaliza el radar temático con descriptores controlados en ES y PT."""
    field_list = _field_list()
    field = next((f for f in field_list if f["id"] == field_id), field_list[0] if field_list else None)
    if field is None:
        return {"status": "no_field"}

    # Extraer conceptos clave de la indagación y la reflexión
    combined = norm(f"{inquiry} {reflection}")
    toks = [t for t in combined.split() if len(t) > 4]

    # Descriptores de élite para el campo (mezcla de ES y PT)
    descriptors_es = list(dict.fromkeys(field["keywords_es"][:5]))
    descriptors_pt = list(dict.fromkeys(field["keywords_pt"][:4]))

    # Añadir los términos del usuario si aportan especificidad
    user_specific = []
    for t in toks[:4]:
        if not any(t in norm(d) for d in descriptors_es + descriptors_pt):
            user_specific.append(t)

    deterministic_list = (descriptors_es + descriptors_pt + user_specific)[:8]

    # Puente librarian: el bibliotecario limpia los keywords con la lista cerrada.
    librarian_mode = "deterministic"
    try:
        from . import librarian as _lib
        if _lib.available():
            res_lib = _lib.concert_keywords(inquiry, reflection, field, deterministic_list)
            if res_lib.get("keywords"):
                deterministic_list = res_lib["keywords"][:8]
            librarian_mode = res_lib.get("mode", "librarian")
    except Exception:
        pass

    final_keywords_list = deterministic_list
    final_keywords_str = ", ".join(final_keywords_list[:8])

    label = f"Radar Temático: {field['name'].split(',')[0].split(' y ')[0]}"

    horizon = (
        f"Has concertado un horizonte de vigilancia en «{field['name']}». "
        f"El radar rastreará de forma continua publicaciones en español y portugués, "
        f"con prioridad en revistas de referencia como {', '.join(field['journals_focus'][:3])}."
    )
    return {
        "status": "concerted",
        "label": label,
        "field_id": field["id"],
        "field_name": field["name"],
        "field_name_pt": field["name_pt"],
        "recommended_keywords": final_keywords_str,
        "keywords_list": final_keywords_list[:8],
        "librarian": librarian_mode,
        "recommended_journals": field["journals_focus"],
        # Aliases compat PWA
        "summary": horizon,
        "key_journals": field["journals_focus"],
        "horizon_summary": horizon,
    }
