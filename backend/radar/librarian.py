"""Librarian: el bibliotecario de Thinkuy (Mistral vía LM Studio).

Filosofía:
- El catálogo manda (SQLite + matching determinista + Pajek).
- El librarian solo traduce: escucha en lenguaje natural, pregunta para precisar
  y propone descriptores controlados. Nunca inventa holdings.
- Si no hay evidencia, se calla. Si el LLM falla, degrada a determinista.

Habla OpenAI-compatible: funciona con LM Studio (http://localhost:1234/v1),
Mistral API, o cualquier endpoint /chat/completions.
"""
from __future__ import annotations

import json
import os
import re

import httpx

from . import profile

LLM_API = os.environ.get("THINKUY_LLM_API", "").rstrip("/")
LLM_MODEL = os.environ.get("THINKUY_LLM_MODEL", "qwen2.5-coder-7b-instruct")


def _api_base() -> str:
    """URL del bibliotecario: env manda, si no el api_base del perfil activo."""
    if LLM_API:
        return LLM_API
    try:
        b = str((profile.field_profile.llm or {}).get("api_base") or "").rstrip("/")
        return b
    except Exception:
        return ""


_LLM_LIVENESS: tuple[float, bool] = (0.0, False)


def available() -> bool:
    """¿Está el bibliotecario de turno? Requiere URL (env o perfil) + perfil habilitado + endpoint vivo."""
    global _LLM_LIVENESS
    try:
        enabled = bool(profile.field_profile.llm.get("enabled", False))
    except Exception:
        enabled = False
    api = _api_base()
    if not (api and enabled):
        return False

    import time
    now = time.time()
    last_check, is_alive = _LLM_LIVENESS
    if now - last_check < 10.0:
        return is_alive

    try:
        r = httpx.get(f"{api}/models", timeout=0.8)
        alive = (r.status_code == 200)
    except Exception:
        alive = False

    _LLM_LIVENESS = (now, alive)
    return alive


_DETECTED_MODEL: str | None = None


def _get_active_model() -> str:
    """Detecta el modelo activo en LM Studio / OpenAI endpoint si es posible."""
    global _DETECTED_MODEL
    configured = _effective_model()
    if _DETECTED_MODEL:
        return _DETECTED_MODEL
    api = _api_base()
    if not api:
        return configured
    try:
        r = httpx.get(f"{api}/models", timeout=3.0)
        if r.status_code == 200:
            data = r.json()
            models = [m.get("id") for m in data.get("data", []) if m.get("id")]
            if configured in models:
                _DETECTED_MODEL = configured
                return configured
            if models:
                _DETECTED_MODEL = models[0]
                return models[0]
    except Exception:
        pass
    return configured


def _chat(system: str, user: str, temperature: float = 0.2,
          max_tokens: int = 400, timeout: float = 5.0,
          model: str | None = None) -> str:
    model_name = model or _get_active_model()
    body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    resp = httpx.post(f"{_api_base()}/chat/completions", json=body, timeout=timeout,
                      headers={"Content-Type": "application/json"})
    if resp.status_code >= 400:
        err_msg = ""
        try:
            err_json = resp.json()
            err_msg = err_json.get("error", {}).get("message") or str(err_json.get("error"))
        except Exception:
            err_msg = resp.text[:300]
        raise RuntimeError(f"LM Studio ({resp.status_code}): {err_msg or resp.reason_phrase}")
    data = resp.json()
    return str(data["choices"][0]["message"]["content"]).strip()


def _extract_json(raw: str) -> dict | None:
    """Extrae JSON tolerando fences markdown y texto extra del LLM."""
    try:
        t = raw.strip()
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```$", "", t)
        m = re.search(r"\{.*\}", t, re.DOTALL)
        return json.loads(m.group(0) if m else t)
    except Exception:
        return None


def _extract_numbered(raw: str, limit: int = 2) -> list[str]:
    """Plan B: si el modelo devuelve '1. ... 2. ...' sin JSON, igual rescatamos."""
    lines = [l.strip(" -•\t") for l in re.split(r"\n+", raw) if l.strip()]
    qs = []
    for l in lines:
        m = re.match(r"^(?:\d+[.)\-:]|[-•])\s*(.+\?)\s*$", l)
        if m:
            qs.append(m.group(1).strip())
        elif l.endswith("?") and len(l) > 20:
            qs.append(l)
        if len(qs) >= limit:
            break
    return qs[:limit]


def _effective_model() -> str:
    """El modelo del perfil manda si existe, si no el de entorno."""
    try:
        m = (profile.field_profile.llm.get("model") or "").strip()
        if m:
            return m
    except Exception:
        pass
    return LLM_MODEL


# ---------------------------------------------------------------- escuchar (home)

_LISTEN_SYSTEM = (
    "Eres el bibliotecario de referencia de Thinkuy. "
    "Escuchas al usuario en lenguaje natural con posibles erratas o abreviaturas.\n"
    "Instrucciones estrictas:\n"
    "1) Corrige la frase a español limpio PRESERVANDO SIEMPRE todos los modificadores "
    "específicos (plataformas, redes sociales, metodologías, ámbitos, países, etc.).\n"
    "2) En 'heard_as', di SIEMPRE: 'Ah, lo que usted busca es <tema con TODOS sus modificadores específicos>'. "
    "NUNCA abrevies ni omitas especificaciones clave como 'en redes sociales', 'en Colombia y España', etc.\n"
    "3) En 'compound_keywords', extrae entre 1 y 4 sintagmas clave compuestos tomados DIRECTAMENTE DE LA CONSULTA DEL USUARIO "
    "(ej. 'ciencia ciudadana en Col y Esp' -> ['ciencia ciudadana', 'Colombia', 'España']; "
    "'comunicación científica en redes sociales' -> ['comunicación científica', 'redes sociales']). "
    "NUNCA reemplaces los términos del usuario por los descriptores generales del campo.\n"
    "4) Elige el field_id más afín de la lista dada por id exacto.\n"
    "5) **Si la consulta NO pertenece a NINGUNO de los campos listados, responde field_id: \"ninguno\".** "
    "No fuerces un campo: es peor disfrazar la consulta con un tema que no le corresponde que "
    "declararla fuera de campo. Ante duda real, responde \"ninguno\".\n"
    "REGLAS: no inventes campos fuera de la lista, no cites papers.\n"
    "Devuelve SOLO JSON: {\"corrected\": \"...\", \"heard_as\": \"Ah, lo que usted busca es ...\", "
    "\"compound_keywords\": [\"...\"], \"field_id\": \"...\", \"confidence\": \"high|low\"}."
)


def listen(inquiry: str, fields: list[dict]) -> dict:
    """Escucha natural -> frase corregida + campo + 'entendí'. Con fallback."""
    clean_inquiry = inquiry.strip()
    if not clean_inquiry:
        return {"mode": "deterministic", "corrected": "", "heard_as": "", "field_id": ""}

    # Detección y resolución automática si el usuario ingresa un DOI o URL con DOI
    doi_match = re.search(r"(10\.\d{4,9}/[^\s]+)", clean_inquiry, re.IGNORECASE)
    if doi_match:
        doi_val = doi_match.group(1).rstrip("/.,;)")
        try:
            with httpx.Client(timeout=4.0) as client:
                r_cr = client.get(
                    f"https://api.crossref.org/works/{doi_val}",
                    headers={"User-Agent": "mailto:info@thinkuy.org"}
                )
                if r_cr.status_code == 200:
                    msg = r_cr.json().get("message", {})
                    titles = msg.get("title") or []
                    if titles and titles[0]:
                        clean_inquiry = titles[0].strip()
        except Exception:
            pass

    if not available():
        default_fid = str(fields[0].get("id")) if fields else profile.field_profile.id
        clean_topic = re.sub(r"^(?:busco\s+(?:informaci[oó]n\s+)?(?:sobre\s+)?|quisiera\s+saber\s+sobre\s+|me\s+interesa\s+)", "", clean_inquiry, flags=re.IGNORECASE).strip()
        chunks = [c.strip() for c in re.split(r'\b(?:en|de|del|sobre|para|con|por|hacia|desde|em|com)\b', clean_topic, flags=re.IGNORECASE) if c.strip() and len(c.strip()) > 2]
        return {
            "mode": "deterministic",
            "corrected": clean_inquiry,
            "field_id": default_fid,
            "heard_as": f"Ah, lo que usted busca es {clean_topic}",
            "compound_keywords": chunks or [clean_topic],
            "confidence": "low",
            "warning": "Librarian apagado (api_base + perfil.llm.enabled)."
        }

    catalog = "\n".join(
        f"- {f.get('id')}: {f.get('name')} | {f.get('description','')[:120]} | "
        f"ej: {', '.join((f.get('keywords_es') or [])[:4])}"
        for f in fields[:10]
    )
    user = f"Campos:\n{catalog}\nFrase del usuario: {clean_inquiry}\nDevuelve el JSON."
    try:
        raw = _chat(_LISTEN_SYSTEM, user, temperature=0.1, max_tokens=300)
        data = _extract_json(raw) or {}
        corrected = str(data.get("corrected") or clean_inquiry).strip()
        field_id = str(data.get("field_id") or "").strip()
        heard = str(data.get("heard_as") or "").strip()
        conf = str(data.get("confidence") or "low").strip()
        compound_kws = [str(k).strip() for k in data.get("compound_keywords", []) if str(k).strip()]

        # Asegurar formato cálido de biblioteca: "Ah, lo que usted busca es ..."
        clean_topic = re.sub(
            r"^(?:busco\s+(?:informaci[oó]n\s+)?(?:sobre\s+)?|quisiera\s+saber\s+sobre\s+|me\s+interesa\s+|investigo\s+(?:sobre\s+)?)",
            "", corrected, flags=re.IGNORECASE
        ).strip()
        if not heard or not heard.lower().startswith("ah,") or heard.lower() == clean_inquiry.lower():
            heard = f"Ah, lo que usted busca es {clean_topic}"
        else:
            # Si el modelo abrevió de más omitiendo contexto específico clave de clean_topic:
            clean_lower = clean_topic.lower()
            heard_lower = heard.lower()
            # Si faltan palabras clave importantes de la consulta:
            topic_words = [w for w in re.findall(r"\b[a-záéíóúüñ]{4,}\b", clean_lower)
                           if w not in {"para", "como", "esta", "este", "entre", "desde", "hacia", "sobre"}]
            missing_words = [w for w in topic_words if w not in heard_lower]
            if len(missing_words) >= 2 or any(m in clean_lower and m not in heard_lower for m in ["redes", "sociales", "colombia", "españa", "tiktok", "salud"]):
                heard = f"Ah, lo que usted busca es {clean_topic}"

        # Validar o mapear campo afín tolerante.
        # **Salida de campo («ninguno»)**: si la consulta no pertenece a ninguno de los campos
        # del perfil activo, se declara. Forzarla al campo más parecido es exactamente lo que
        # volvía monotemática la herramienta cuando `comunicacion` era el perfil por defecto
        # (una consulta clínica acababa etiquetada como «Ecología de los Medios»).
        FUERA_DE_CAMPO = {"ninguno", "ningun", "ninguna", "none", "fuera", "fuera_del_campo",
                          "no_aplica", "n/a", ""}
        if str(field_id).strip().lower() in FUERA_DE_CAMPO and fields:
            return {"mode": "librarian", "corrected": corrected, "field_id": "ninguno",
                    "heard_as": heard, "compound_keywords": compound_kws, "confidence": conf,
                    "fuera_del_campo": True}

        valid_ids = {str(f.get("id")) for f in fields}
        if field_id not in valid_ids:
            field_lower = field_id.lower()
            matched_id = None
            for f in fields:
                fid = str(f.get("id", ""))
                fname = str(f.get("name", "")).lower()
                if fid.lower() in field_lower or field_lower in fid.lower() or fname in field_lower:
                    matched_id = fid
                    break
            if not matched_id and fields:
                # Antes se caía al PRIMER campo del perfil sin comprobar nada. Eso disfrazaba
                # cualquier consulta ajena con el tema más parecido del campo activo.
                matched_id = "ninguno"
            field_id = matched_id or profile.field_profile.id

        return {"mode": "librarian", "corrected": corrected,
                "field_id": field_id, "heard_as": heard, "compound_keywords": compound_kws,
                "confidence": conf}
    except Exception as e:
        default_fid = str(fields[0].get("id")) if fields else profile.field_profile.id
        clean_topic = re.sub(r"^(?:busco\s+(?:informaci[oó]n\s+)?(?:sobre\s+)?|quisiera\s+saber\s+sobre\s+|me\s+interesa\s+|investigo\s+(?:sobre\s+)?)", "", clean_inquiry, flags=re.IGNORECASE).strip()
        return {
            "mode": "deterministic",
            "corrected": clean_inquiry,
            "field_id": default_fid,
            "heard_as": f"Ah, lo que usted busca es {clean_topic}",
            "compound_keywords": [],
            "confidence": "low",
            "warning": f"Bibliotecario no pudo escuchar: {type(e).__name__}"
        }


# ---------------------------------------------------------------- auditor de ecosistemas (diagnóstico grounded)

_EXPLAIN_SYSTEM = (
    "Eres el Auditor de Ecosistemas Científicos de Thinkuy. Tu misión es analizar la "
    "radiografía bibliométrica del corpus recuperado (SciELO, Redalyc, OpenAlex, Crossref) "
    "con prudencia epistemológica y cero alucinaciones.\n"
    "DIRECTRICES DE RIGOR Y CERO GENERALIZACIONES:\n"
    "1) Usa EXCLUSIVAMENTE los datos proporcionados (volumen real recuperado, revistas, autores y saturación).\n"
    "2) Anclaje honesto de alcance: NUNCA afirmes que una disciplina 'se centra principalmente' en una o dos revistas "
    "a partir de una muestra limitada. Di con rigor: 'Dentro del acervo examinado (sea catálogo local indexado o sonda global OpenAlex), "
    "se registran contribuciones en publicaciones como...'. Si la cobertura local es escasa, advierte con transparencia que "
    "se trata de apariciones puntuales dentro del acervo y no necesariamente de la totalidad del campo.\n"
    "3) Redacta en 2 párrafos concisos y fluidos (sin viñetas ni encabezados markdown):\n"
    "   - Párrafo 1: Cobertura de documentos recuperados en el acervo y revistas donde aparecen dichas publicaciones.\n"
    "   - Párrafo 2: Autores con aportes registrados en la muestra y diagnóstico de saturación o vacíos de investigación.\n"
    "4) Jamás inventes citas, instituciones ni afirmaciones que no figuren en los datos."
)


def explain_results(inquiry: str, heard_as: str, articles: list[dict],
                    field: dict | None = None, keywords: list[str] | None = None,
                    ecosystem: dict | None = None, saturation: dict | None = None,
                    data_source: str = "catalog") -> str:
    """Redacta un diagnóstico de ecosistema grounded, conciso y académico."""
    is_probe = data_source == "live_probe"
    if not articles:
        topic = heard_as.replace("Ah, lo que usted busca es", "").strip() or inquiry
        return (
            f"El radar ha examinado el acervo para «{topic}», pero no se registran publicaciones "
            "con coincidencia directa en el corpus actual de Iberoamérica. Representa un vacío de "
            "cobertura en las revistas indexadas del campo."
        )

    eco = ecosystem or {}
    sat = saturation or {}
    total_docs = eco.get("total_matched", len(articles))
    top_journals = [j.get("name") for j in (eco.get("top_journals") or []) if j.get("name")]
    top_authors = [a.get("name") if isinstance(a, dict) else str(a) for a in (eco.get("top_authors") or [])]
    sat_label = sat.get("label", "Exploración bibliométrica")
    sat_desc = sat.get("description", "")
    topics_str = ", ".join((keywords or [])[:3]) or (field.get("name") if field else "el área temática")

    journals_text = ", ".join(top_journals[:3]) if top_journals else "publicaciones indexadas"
    authors_text = ", ".join(top_authors[:3]) if top_authors else "diversos investigadores"

    corpus_scope = "en acceso abierto global (Sonda OpenAlex / Crossref)" if is_probe else "en el repositorio importado"

    if not available():
        # Fallback determinista impecable (cero IA, 100% verídico)
        return (
            f"El radar localizó {total_docs} documentos {corpus_scope} vinculados a {topics_str}. "
            f"Dentro de este corpus, se registran publicaciones en medios como {journals_text}, junto a aportes de {authors_text}. "
            f"Diagnóstico de cobertura: {sat_label} ({sat_desc})."
        )

    field_name = field.get("name", "") if field else ""
    sample_titles = [f"- \"{a.get('title')}\" ({a.get('journal_title') or a.get('journal') or ''})"
                     for a in articles[:4]]

    catalog_label = "Total obras globales en Acceso Abierto (Sonda OpenAlex / Crossref)" if is_probe else "Total documentos en repositorio importado"

    context = (
        f"Inquietud: {inquiry}\n"
        f"Interpretación: {heard_as}\n"
        f"Campo: {field_name}\n"
        f"Origen de datos: {'Sonda en Vivo multidisciplinar OpenAlex / Crossref' if is_probe else 'Repositorio importado'}\n"
        f"Métricas del Ecosistema:\n"
        f"- {catalog_label}: {total_docs}\n"
        f"- Revistas con presencia en la muestra: {journals_text}\n"
        f"- Autores destacados en la muestra: {authors_text}\n"
        f"- Diagnóstico de saturación: {sat_label} — {sat_desc}\n"
        f"- Muestra de obras clave:\n" + "\n".join(sample_titles)
    )

    try:
        return _chat(_EXPLAIN_SYSTEM, context, temperature=0.2, max_tokens=400)
    except Exception:
        return (
            f"El radar localizó {total_docs} documentos {corpus_scope} vinculados a {topics_str}. "
            f"Dentro de este corpus, se registran publicaciones en medios como {journals_text}, junto a aportes de {authors_text}. "
            f"Diagnóstico de cobertura: {sat_label} ({sat_desc})."
        )


# ---------------------------------------------------------------- preguntas vivas

_SOCRATIC_SYSTEM = (
    "Eres el bibliotecario de referencia de Thinkuy, radar de comunicación "
    "científica abierta (SciELO, Redalyc, OpenAlex). Hablas español académico, "
    "cálido y preciso. Tu tarea: ayudar a precisar una inquietud de investigación. "
    "REGLAS DURAS: 1) Formula exactamente 2 preguntas socráticas, cortas "
    "(máximo 25 palabras cada una), que obliguen a elegir vertiente dentro del "
    "campo dado. 2) No inventes conceptos fuera del campo ni cites papers. "
    "3) Devuelve SOLO un JSON: {\"questions\": [\"...\", \"...\"]}. Sin texto extra."
)


def socratic_questions(inquiry: str, field: dict,
                       fallback: list[str] | None = None) -> dict:
    """Genera 2 preguntas vivas con Mistral. Si falla, devuelve las fijas."""
    fallback = fallback or []
    if not available():
        return {"questions": fallback, "mode": "deterministic",
                "warning": "Librarian apagado (THINKUY_LLM_API + perfil.llm.enabled)."}
    field_name = field.get("name", "")
    field_desc = field.get("description", "")
    focus = ", ".join((field.get("journals_focus") or [])[:3])
    user = (
        f"Campo: {field_name}\nDescripción: {field_desc}\n"
        f"Revistas foco: {focus}\nInquietud del investigador: {inquiry}\n"
        "Devuelve el JSON con las 2 preguntas."
    )
    try:
        raw = _chat(_SOCRATIC_SYSTEM, user, temperature=0.3, max_tokens=300)
        data = _extract_json(raw) or {}
        qs = [str(q).strip() for q in data.get("questions", []) if str(q).strip()]
        if not qs:
            qs = _extract_numbered(raw, 2)
        if len(qs) >= 2:
            return {"questions": qs[:2], "mode": "librarian"}
        if qs:
            return {"questions": (qs + fallback)[:2], "mode": "librarian_partial"}
    except Exception as e:
        return {"questions": fallback, "mode": "deterministic",
                "warning": f"Librarian falló y degradó a plantillas: {type(e).__name__}"}
    return {"questions": fallback, "mode": "deterministic"}


# ------------------------------------------------------- concertar descriptores

_CONCERT_SYSTEM = (
    "Eres el bibliotecario de Thinkuy. Traduces lenguaje natural a descriptores "
    "controlados del catálogo. REGLAS DURAS: 1) Elige de la lista cerrada de "
    "descriptores ES/PT dada; puedes agregar máximo 2 términos nuevos del usuario "
    "si aportan especificidad (una palabra, minúsculas, sin acentos innecesarios). "
    "2) Devuelve SOLO un JSON: {\"keywords\": [\"...\", ...]} con máximo 8 items. "
    "3) Nada de frases largas ni explicaciones."
)


def concert_keywords(inquiry: str, reflection: str, field: dict,
                     fallback: list[str] | None = None) -> dict:
    """Propone hasta 8 keywords controlados con Mistral, con fallback determinista."""
    fallback = fallback or []
    if not available():
        return {"keywords": fallback[:8], "mode": "deterministic"}
    descriptors = list(dict.fromkeys(
        (field.get("keywords_es") or [])[:5] + (field.get("keywords_pt") or [])[:4]
    ))
    user = (
        f"Descriptores permitidos: {', '.join(descriptors)}\n"
        f"Inquietud: {inquiry}\nReflexión del usuario: {reflection}\n"
        "Devuelve el JSON con los keywords."
    )
    try:
        raw = _chat(_CONCERT_SYSTEM, user, temperature=0.2, max_tokens=250)
        data = _extract_json(raw) or {}
        kws = [str(k).strip() for k in data.get("keywords", []) if str(k).strip()]
        kws = list(dict.fromkeys(kws))[:8]
        if kws:
            return {"keywords": kws, "mode": "librarian"}
    except Exception as e:
        return {"keywords": fallback[:8], "mode": "deterministic",
                "warning": f"Librarian falló: {type(e).__name__}"}
    return {"keywords": fallback[:8], "mode": "deterministic"}


# ------------------------------------------------------------- síntesis final

_SYNTH_SYSTEM = (
    "Eres el bibliotecario de Thinkuy. Recibes una bandeja con fragmentos "
    "literales reales (cada uno con DOI). REGLAS DURAS: 1) Informe en capas: "
    "respuesta directa, hallazgos clave con DOIs entre paréntesis, "
    "contradicciones si las hay, tres preguntas focales. 2) SOLO cita DOIs de "
    "la bandeja. 3) Sin evidencia → marca [SIN EVIDENCIA EN EL CORPUS]. "
    "4) Español académico, formal y neutral, máximo 400 palabras."
)


def synthesize(pack: dict) -> str:
    """Redacta el informe en capas solo con la bandeja dada."""
    evidence = [
        {"doi": i.get("doi"), "title": i.get("title"), "year": i.get("year"),
         "journal": i.get("journal"), "fragment": i.get("fragment"),
         "stance": i.get("stance")}
        for i in pack.get("items", [])
    ]
    user = "Bandeja (JSON):\n" + json.dumps(
        {"topic": pack.get("topic"), "evidence": evidence}, ensure_ascii=False)
    return _chat(_SYNTH_SYSTEM, user, temperature=0.2, max_tokens=1200)


# ------------------------------------------------- interpretación de citación (etapa 2)

CITATION_FUNCTIONS = (
    "supporting_or_agreement",
    "contrasting_or_refuting",
    "methodological_adoption",
    "neutral_or_mention",
)

_CLASSIFY_SYSTEM = (
    "Eres un asistente de apoyo epistemológico al investigador científico (español, portugués e inglés). "
    "Tu labor es formular hipótesis interpretativas tentativas para apoyar el análisis crítico del investigador, "
    "recordando en todo momento que la IA es un instrumento de apoyo y NUNCA un reemplazo del criterio humano.\n"
    "Dado un pasaje donde un trabajo cita a otro, clasifica la FUNCIÓN de la cita y extrae "
    "el CLAIM: la afirmación literal exacta que el citante hace sobre el citado.\n"
    "Funciones (usa EXACTAMENTE una de estas cadenas):\n"
    "- supporting_or_agreement: posible consenso (sugiere que el autor respalda, confirma, coincide o extiende la tesis).\n"
    "- contrasting_or_refuting: posible disenso (sugiere que el autor contrasta, matiza, cuestiona o discrepa).\n"
    "- methodological_adoption: posible adopción metodológica (sugiere que adopta o adapta método, instrumento o protocolo).\n"
    "- neutral_or_mention: posible mención contextual (mención de estado del arte o contexto sin postura evidente).\n"
    "REGLAS: 1) El claim debe ser una cita LITERAL del pasaje (máximo 40 palabras); "
    "si no hay afirmación identificable, claim vacío. "
    "2) Devuelve SOLO un JSON array: "
    "[{\"idx\": 0, \"function\": \"...\", \"claim\": \"...\", \"confidence\": \"high|low\"}]. Sin texto extra."
)

_CLASSIFY_EXAMPLE = (
    "Ejemplo: pasaje «Como señalan Torres-Salinas et al. (2013), las altmétricas "
    "complementan la evaluación tradicional» → [{\"idx\": 0, "
    "\"function\": \"supporting_or_agreement\", "
    "\"claim\": \"las altmétricas complementan la evaluación tradicional\", "
    "\"confidence\": \"high\"}]."
)


def _extract_json_list(raw: str) -> list | None:
    """Extrae un JSON array tolerando fences y texto extra."""
    try:
        t = raw.strip()
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```$", "", t)
        m = re.search(r"\[.*\]", t, re.DOTALL)
        return json.loads(m.group(0) if m else t)
    except Exception:
        return None


def _verbatim(claim: str, paragraph: str) -> bool:
    """Anti-alucinación: el claim debe aparecer literal en el párrafo."""
    c = " ".join(str(claim or "").split()).lower()
    p = " ".join(str(paragraph or "").split()).lower()
    return bool(c) and c in p


def _classify_model() -> str:
    """Modelo para interpretación de citas: override dedicado o el activo.

    Orden: THINKUY_CLASSIFY_MODEL (env) → perfil llm.classify_model →
    modelo activo del perfil. No altera al resto de funciones del bibliotecario.
    """
    env_m = (os.environ.get("THINKUY_CLASSIFY_MODEL") or "").strip()
    if env_m:
        return env_m
    try:
        m = (profile.field_profile.llm.get("classify_model") or "").strip()
        if m:
            return m
    except Exception:
        pass
    return _get_active_model()


def classify_citation_functions(items: list[dict], batch_size: int = 20) -> list[dict]:
    """Clasifica la función retórica de contextos de citación con el LLM local.

    Entrada: [{paragraph, sentence, cited_label?}]. Salida alineada por idx:
    [{function, claim (literal o None), confidence}]. Si el bibliotecario está
    apagado o falla, devuelve [] y el llamador conserva la heurística.
    """
    if not items or not available():
        return []
    model_name = _classify_model()
    out: list[dict] = []
    for start in range(0, len(items), max(1, batch_size)):
        chunk = items[start:start + max(1, batch_size)]
        payload = [
            {
                "idx": i,
                "pasaje": (it.get("paragraph") or "")[:1500],
                "oracion": (it.get("sentence") or "")[:400],
            }
            for i, it in enumerate(chunk)
        ]
        user = _CLASSIFY_EXAMPLE + "\nClasifica estos pasajes:\n" + json.dumps(
            payload, ensure_ascii=False)
        try:
            # Timeout amplio: un servidor local puede tardar en cargar el modelo en VRAM.
            raw = _chat(_CLASSIFY_SYSTEM, user, temperature=0.1,
                        max_tokens=400 + 150 * len(chunk), timeout=120,
                        model=model_name)
            data = _extract_json_list(raw) or []
        except Exception:
            return []
        by_idx = {d.get("idx"): d for d in data if isinstance(d, dict)}
        for i, it in enumerate(chunk):
            d = by_idx.get(i) or {}
            fn = d.get("function")
            claim = str(d.get("claim") or "").strip()
            para = it.get("paragraph") or ""
            if fn not in CITATION_FUNCTIONS:
                out.append({"function": None, "claim": None, "confidence": "low"})
                continue
            if claim and not _verbatim(claim, para):
                out.append({"function": fn, "claim": None, "confidence": "low"})
                continue
            out.append({
                "function": fn,
                "claim": claim or None,
                "confidence": d.get("confidence") if d.get("confidence") in ("high", "low") else "low",
            })
    return out


# ------------------------------------------------- clasificación retórica de posturas en controversias

_STANCE_SYSTEM = (
    "Eres un clasificador retórico y epistemológico de literatura científica. "
    "Tu tarea es evaluar la postura tentativa de un artículo científico frente a una pregunta o tema de investigación.\n"
    "Categorías posibles (usa EXACTAMENTE una):\n"
    "- supporting: posible consenso (apoya, confirma, valida, halla evidencia empírica a favor de la hipótesis o tema).\n"
    "- contradicting: posible disenso (cuestiona, contradice, refuta, encuentra límites o evidencia inconsistente con la tesis).\n"
    "- methodological: posible adopción metodológica (estudio centrado en diseño, validación de instrumentos o protocolos).\n"
    "- mixed: posible mención contextual (mención de estado del arte, revisión descriptiva o postura no concluyente/ambivalente).\n"
    "REGLA: Devuelve SOLO un JSON array de objetos: "
    "[{\"idx\": 0, \"stance\": \"supporting|contradicting|methodological|mixed\", \"rationale\": \"breve explicacion (max 15 palabras)\", \"confidence\": \"high|low\"}]. Sin texto extra."
)


def classify_topic_stances_ai(items: list[dict], topic: str, batch_size: int = 15) -> list[dict]:
    """Clasifica la postura retórica de artículos frente a un tema usando el LLM local."""
    if not items or not available():
        return []
    model_name = _classify_model()
    out: list[dict] = []
    valid_stances = {"supporting", "contradicting", "methodological", "mixed"}

    for start in range(0, len(items), max(1, batch_size)):
        chunk = items[start:start + max(1, batch_size)]
        payload = [
            {
                "idx": i,
                "titulo": (it.get("title") or "")[:200],
                "resumen": (it.get("abstract") or it.get("fragment") or "")[:600],
            }
            for i, it in enumerate(chunk)
        ]
        user = f"Tema de investigación: «{topic}»\nClasifica la postura de los siguientes resúmenes:\n" + json.dumps(
            payload, ensure_ascii=False)
        try:
            raw = _chat(_STANCE_SYSTEM, user, temperature=0.1,
                        max_tokens=200 + 100 * len(chunk), timeout=60,
                        model=model_name)
            data = _extract_json_list(raw) or []
        except Exception:
            return []

        by_idx = {d.get("idx"): d for d in data if isinstance(d, dict)}
        for i, _it in enumerate(chunk):
            d = by_idx.get(i) or {}
            st = str(d.get("stance") or "").strip().lower()
            if st not in valid_stances:
                st = "mixed"
            out.append({
                "stance": st,
                "rationale": str(d.get("rationale") or "").strip() or None,
                "confidence": d.get("confidence") if d.get("confidence") in ("high", "low") else "low",
            })
    return out


# ------------------------------------------------- agente A.1 revisión sistemática (metodólogo)

_METHODOLOGIST_SYSTEM = (
    "# ROL\n"
    "Eres un Metodólogo Experto en Revisiones Sistemáticas de la Literatura y Síntesis "
    "de Evidencia Científica (PRISMA 2020). Tu objetivo es ejecutar una revisión sistemática "
    "completa, rigurosa y transparente en 7 fases, de forma secuencial y sin pausas.\n"
    "\n"
    "# REGLAS DE ORO (INQUEBRANTABLES)\n"
    "1. Cero Alucinaciones: NO inventes artículos. Usa EXCLUSIVAMENTE el corpus de artículos "
    "verificados que te proporcionará tu motor de radar bibliométrico (con DOIs reales).\n"
    "2. Idioma: Toda la salida, análisis y redacción será en ESPAÑOL. Las cadenas de búsqueda "
    "(queries) se generarán en INGLÉS para maximizar cobertura.\n"
    "3. Transparencia: Al final, incluirás obligatoriamente una 'Declaración de uso de IA y "
    "Motor Bibliométrico'.\n"
    "4. Heurística de Muestra: Una buena revisión sistemática debe incluir entre 30 y 300 "
    "artículos. Si el motor devuelve <30, el tema es muy específico; si devuelve >300, es "
    "inmanejable y debes sugerir filtros más estrictos.\n"
    "\n"
    "# FASES DE EJECUCIÓN (Mostrar una línea de estado breve al terminar cada una)\n"
    "\n"
    "## Fase 1: Formulación PICOS (Específica, Relevante y Factible)\n"
    "Desglosa la pregunta del usuario en: P (Población), I (Intervención/Exposición), "
    "C (Comparador), O (Outcome medible), S (Study Design: RCT, Meta-análisis...).\n"
    "\n"
    "## Fase 2: Estrategia de Búsqueda Booleana (Enfoque TITLE-ABS-KEY)\n"
    "Diseña la cadena simulando el operador TITLE-ABS-KEY de Scopus (Título, Resumen y "
    "Palabras Clave). Bloques P, I y O con OR interno (sinónimos y abreviaturas) y AND entre bloques.\n"
    "\n"
    "## Fase 3: Cribado y Diagrama PRISMA 2020\n"
    "Identificados (total del radar) → Tamizados (sin duplicados por DOI) → Elegibilidad "
    "(título/resumen) → Incluidos. Valida el rango óptimo de 30 a 300 artículos.\n"
    "\n"
    "## Fase 4: Extracción de Datos y Verificación\n"
    "Tabla Markdown con EXACTAMENTE: Título | Descripción Breve (sin copiar el abstract) | "
    "Año | Muestra (N) | Metodología | Resultados Clave | Conclusiones. Verifica cada título "
    "contra el corpus del radar.\n"
    "REGLAS CRÍTICAS PARA LA TABLA (ANTI-ALUCINACIÓN Y ANTI-COPIA):\n"
    "- CORRESPONDENCIA BIUNÍVOCA 1:1: Cada fila debe describir ÚNICA y exclusivamente el contenido singular del artículo de esa fila. "
    "Está TERMINANTEMENTE PROHIBIDO arrastrar, copiar o propagar la temática de un artículo a filas contiguas. "
    "Si un artículo analiza TikTok, otro analiza diplomacia en la ONU y otro analiza cambio climático en WhatsApp, cada fila debe reflejar su propio tema específico.\n"
    "- IDIOMA: Todo el texto debe estar en ESPAÑOL académico. Si el abstract o título original está en portugués o inglés, "
    "traduce y redacta en español la descripción, metodología, resultados y conclusiones.\n"
    "- MUESTRA (N): Extrae la cifra empírica exacta si está declarada (ej. 'N=1.200 votantes', 'N=450 videos', 'N=35 discursos'). "
    "Si el estudio es teórico/conceptual sin trabajo de campo, escribe 'Estudio conceptual/teórico'. Si es una revisión de literatura, "
    "escribe 'Revisión documental'. Si es empírico pero no declara el número exacto, escribe 'No declarada'. PROHIBIDO poner 'N/A' genérico.\n"
    "- PRIORIDAD DE CHARTING VERIFICADO: Si el artículo incluye el campo 'charting_verificado', usa obligatoriamente esos datos para llenar la fila.\n"
    "\n"
    "## Fase 5: Evaluación de Riesgo de Sesgo (Opcional)\n"
    "Advertencia metodológica sobre limitaciones comunes de los diseños encontrados.\n"
    "\n"
    "## Fase 6: Síntesis de la Evidencia\n"
    "Evalúa metaanálisis si hay homogeneidad; si no, síntesis narrativa: temas emergentes "
    "(Positiva/Negativa/Mixta), contradicciones con explicaciones y lagunas (knowledge gaps).\n"
    "\n"
    "## Fase 7: Informe Final y Estructura del Artículo (El 'Paper')\n"
    "Título sugerido, abstract estructurado, introducción, métodos (protocolo PRISMA y "
    "criterios), resultados, discusión (implicaciones y limitaciones) y declaración de uso "
    "de IA asistida por motor de radar bibliométrico."
)


def _norm_title(text: str | None) -> str:
    """Normalización liviana para cotejar títulos del informe contra el corpus."""
    t = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    return t.strip("\"'“”‘’()[] ")


def audit_extraction(report: str | None, corpus: list[dict]) -> dict:
    """Anti-alucinación Fase 4: verifica que lo extraído exista en el corpus.

    Revisa filas de tablas Markdown (primera celda = título) y DOIs citados en
    el informe contra el corpus enviado al LLM. Devuelve hallazgos, no veredicto.
    """
    corpus_titles = {_norm_title(a.get("title")) for a in (corpus or []) if a.get("title")}
    corpus_dois = {(a.get("doi") or "").strip().lower() for a in (corpus or []) if a.get("doi")}
    text = report or ""
    rows_checked = 0
    unmatched: list[dict] = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[0]:
            continue
        if all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells):
            continue  # fila separadora Markdown
        if re.search(r"t[ií]tulo|title|descricao|description", cells[0], re.IGNORECASE):
            continue
        rows_checked += 1
        title = _norm_title(cells[0])
        if not title:
            continue
        ok = title in corpus_titles or any(
            (len(title) > 25 and title in ct) or (len(ct) > 25 and ct in title)
            for ct in corpus_titles
        )
        if not ok:
            unmatched.append({"row": rows_checked, "title": cells[0][:120]})
    foreign_dois = sorted({
        m.group(0).lower().rstrip(".,;)")
        for m in re.finditer(r"10\.\d{4,9}/[^\s\"'<>\]\)}]+", text)
        if m.group(0).lower().rstrip(".,;)") not in corpus_dois
    })
    return {"rows_checked": rows_checked, "unmatched": unmatched,
            "foreign_dois": foreign_dois,
            "clean": not unmatched and not foreign_dois}


def run_systematic_review(inquiry: str, corpus: list[dict],
                          max_tokens: int = 3000,
                          engine_note: str | None = None,
                          timeout: float = 300) -> dict:
    """Ejecuta el Agente A.1 Metodólogo sobre un corpus verificado del radar.

    `corpus`: artículos del catálogo con doi/título/resumen reales. El prompt
    prohíbe inventar fuera de ellos. Sin LLM disponible, degradación honesta.
    Protege la ventana de contexto de modelos locales (LM Studio / Ollama).
    """
    valid_articles = [a for a in (corpus or []) if a.get("doi") and a.get("title")]
    if not valid_articles:
        return {"status": "empty",
                "report": "Sin corpus verificado no hay revisión: primero recupera artículos del radar o del protocolo."}
    if not available():
        return {"status": "no_llm", "corpus_count": len(valid_articles),
                "report": ("Bibliotecario apagado (api_base + perfil.llm.enabled). "
                           f"Corpus verificado listo con {len(valid_articles)} artículos; "
                           "enciende el LLM para generar el informe PRISMA.")}

    def _build_user_prompt(sample_size: int, abstract_max: int) -> tuple[str, list[dict]]:
        sample = valid_articles[:sample_size]
        items = []
        for a in sample:
            it = {
                "doi": a.get("doi"),
                "title": a.get("title"),
                "year": a.get("year"),
                "journal": a.get("journal_title") or a.get("journal"),
                "abstract": (a.get("abstract") or "")[:abstract_max]
            }
            if a.get("charting"):
                c = a["charting"]
                it["charting_verificado"] = {
                    "poblacion": c.get("population"),
                    "concepto": c.get("concept"),
                    "contexto": c.get("context"),
                    "metodologia": c.get("methodology"),
                    "muestra": c.get("sample_size"),
                    "hallazgos": c.get("key_findings")
                }
            items.append(it)
        u = (f"Pregunta de investigación: {inquiry.strip()}\n"
             f"Corpus verificado del radar ({len(valid_articles)} artículos identificados; "
             f"muestra representativa de {len(items)} artículos para extracción y síntesis, ÚNICA fuente permitida):\n"
             + json.dumps(items, ensure_ascii=False))
        if engine_note:
            u += "\nNota del motor: " + engine_note.strip()
        return u, items

    # Intentamos primero con muestra balanceada (hasta 15 artículos, abstract de 280 caracteres)
    user, prompt_items = _build_user_prompt(sample_size=15, abstract_max=280)
    try:
        report = _chat(_METHODOLOGIST_SYSTEM, user, temperature=0.2,
                       max_tokens=max_tokens, timeout=timeout)
    except Exception as e:
        err_text = str(e).lower()
        # Si el error es por desbordamiento de contexto de LM Studio, reintentar con muestra compacta
        if any(w in err_text for w in ("context", "exceeded", "too long", "length", "token")):
            try:
                compact_user, prompt_items = _build_user_prompt(sample_size=8, abstract_max=160)
                report = _chat(_METHODOLOGIST_SYSTEM, compact_user, temperature=0.2,
                               max_tokens=max_tokens, timeout=timeout)
            except Exception as e2:
                return {"status": "error", "corpus_count": len(valid_articles),
                        "report": f"LM Studio no pudo completar la revisión: {e2}",
                        "warning": str(e2)[:300]}
        else:
            return {"status": "error", "corpus_count": len(valid_articles),
                    "report": f"Bibliotecario no respondió: {e}",
                    "warning": str(e)[:300]}

    return {"status": "ok", "corpus_count": len(valid_articles), "sample_count": len(prompt_items), "report": report}

