"""Auditor Forense Determinista del Dataset Thinkuy V3 (Fase 1 / Gate 1).

NO usa ningun modelo de lenguaje. Todo diagnostico es por regla explicita y
reproducible. Toda fila recibe un veredicto; no existe fallback silencioso.

USO:
    python tools/auditor_forense_dataset.py

SALIDAS:
    data/auditorias_y_benchmarks/dataset_forense_v3.csv     (una fila por ejemplo)
    data/auditorias_y_benchmarks/dataset_forense_v3_resumen.json

REGLAS:
    R1  Clasificar la fila por el ESQUEMA DEL TARGET, no por heuristica de texto.
    R2  Detectar SCHEMA_MISMATCH (prompt de una tarea + target de otra).
    R3  Detectar contradiccion pensamiento <-> etiqueta.
    R4  Detectar campos degenerados: None, repeticiones, ecos del insumo.
    R5  Verificar que el insumo de T2 sea realmente metodologia.
    R6  Verificar grounding lexico de la PCC contra la metodologia inyectada.
    R7  Detectar idioma por fila (ES/PT/EN) sin diagnosticar desde consola.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_PATH = PROJECT_ROOT / "data" / "thinkuy_v3_gold_standard_chatml.jsonl"
OUT_DIR = PROJECT_ROOT / "data" / "auditorias_y_benchmarks"
OUT_CSV = OUT_DIR / "dataset_forense_v3.csv"
OUT_JSON = OUT_DIR / "dataset_forense_v3_resumen.json"

# ---------------------------------------------------------------- taxonomias
ROLES_LEGACY = {"Seminal", "Síntesis_Review", "Teórico_Framework", "Metodológico", "Empírico"}
ROLES_CANONICOS = {"SEMINAL", "SYNTHESIS_REVIEW", "THEORETICAL_FRAMEWORK", "METHODOLOGICAL", "EMPIRICAL"}
ROLES_MAP = {
    "seminal": "SEMINAL",
    "síntesis_review": "SYNTHESIS_REVIEW",
    "sintesis_review": "SYNTHESIS_REVIEW",
    "síntesis": "SYNTHESIS_REVIEW",
    "teórico_framework": "THEORETICAL_FRAMEWORK",
    "teorico_framework": "THEORETICAL_FRAMEWORK",
    "metodológico": "METHODOLOGICAL",
    "metodologico": "METHODOLOGICAL",
    "empírico": "EMPIRICAL",
    "empirico": "EMPIRICAL",
}

TRADICIONES = [
    "Hegemónica", "Medicina Social", "Decolonial", "Ecología de Saberes",
    "Apropiación Social", "Crítica Latinoamericana",
    "Saúde Coletiva", "Epistemologias do Sul", "Educação Popular",
]
STANCES = ["Consenso", "Disenso", "Adopcion_Metodologica", "Mencion_Contextual", "Concesion_Matizacion"]

METHOD_MARKERS = [
    "method", "methods", "methodology", "methodological", "search strategy",
    "inclusion criteria", "eligibility", "prisma", "arksey", "jbi", "pico", "pcc",
    "metodolog", "método", "metodo", "métodos", "criterios de inclusión", "criterios de inclusion",
    "estratégia de busca", "estrategia de busqueda", "revisão sistemática", "revisao sistematica",
    "scoping review", "study design", "data extraction", "extracción de datos",
]
REFERENCE_MARKERS = re.compile(r"\b\d{4};\s*\d+|doi\.org/10\.\d{4,}|https?://doi\.org", re.IGNORECASE)
JOURNAL_RANKING_MARKERS = re.compile(r"\bQ[1-4]\b")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm(text: str) -> str:
    return strip_accents(text or "").lower().strip()


# ---------------------------------------------------------------- degeneracion
DEGEN_CHAR_RUN = re.compile(r"(.)\1{9,}")
DEGEN_TOKEN_REPEAT = re.compile(r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ_]{4,})(?:[_\s]+\1){2,}", re.IGNORECASE)


def find_degenerations(text: str) -> list[str]:
    flags = []
    if not text:
        return ["EMPTY_TARGET"]
    if DEGEN_CHAR_RUN.search(text):
        flags.append("DEGEN_CHAR_RUN")
    if DEGEN_TOKEN_REPEAT.search(text):
        flags.append("DEGEN_TOKEN_REPEAT")
    if "None" in text:
        flags.append("NULL_LEAK")
    if re.search(r"\bUSD\b|```|Assistant:|<\|", text):
        flags.append("CHAT_RESIDUE")
    # target cortado a mitad del JSON de salida
    if re.search(r"<salida_json>", text, re.IGNORECASE):
        if not re.search(r"</salida_json>", text, re.IGNORECASE):
            flags.append("TARGET_TRUNCADO")
        elif extract_json_block(text) is None:
            flags.append("JSON_INVALIDO")
    return flags


def echo_ratio(target: str, source: str) -> float:
    """Proporcion del target que aparece verbatim en el insumo (ventanas de 80 chars)."""
    if not target or not source or len(target) < 80:
        return 0.0
    window = 80
    hits = 0
    total = 0
    for i in range(0, len(target) - window, window):
        total += 1
        if target[i:i + window] in source:
            hits += 1
    return round(hits / total, 3) if total else 0.0


# ---------------------------------------------------------------- idioma
PT_PAT = re.compile(r"ção|ções|\bç\b|ã|\bembora\b|\bainda que\b|\bnão\b|\bResumo\b|\bMétodos\b|\bResultados\b|\bConclusões\b")
ES_PAT = re.compile(r"ción|ciones|ñ|\bno obstante\b|\bResumen\b|\bMétodos\b|\bResultados\b|\bConclusiones\b|\bObjetivo\b")
EN_PAT = re.compile(r"\bthe\b|\bthis study\b|\babstract\b|\bmethods\b|\bresults\b|\bwe\b", re.IGNORECASE)


def detect_language(text: str) -> str:
    if not text:
        return "UNKNOWN"
    pt, es, en = len(PT_PAT.findall(text)), len(ES_PAT.findall(text)), len(EN_PAT.findall(text))
    best = max(pt, es, en)
    if best == 0:
        return "UNKNOWN"
    winners = [name for name, v in (("PT", pt), ("ES", es), ("EN", en)) if v == best]
    return winners[0] if len(winners) == 1 else "UNCERTAIN"


# ---------------------------------------------------------------- extraccion
def extract_json_block(text: str) -> dict | None:
    """Extrae el objeto JSON del target. Devuelve None si no hay JSON parseable."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        # intento de reparacion: quitar comas finales
        candidate = re.sub(r",\s*([}\]])", r"\1", m.group(0))
        try:
            return json.loads(candidate)
        except Exception:
            return None


def extract_thought(text: str) -> str:
    m = re.search(r"<pensamiento>(.*?)</pensamiento>", text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def schema_of(target_json: dict | None) -> str:
    """R2: clasifica por claves reales del target, no por texto."""
    if target_json is None:
        return "NO_JSON"
    keys = set(target_json.keys())
    if {"rol_metodologico"} <= keys:
        return "T1_ROLE"
    if {"poblacion"} & keys or {"concepto"} & keys or {"población"} & keys:
        return "T2_PCC"
    if {"tipo_relacion"} & keys:
        return "T3_STANCE_LEGACY"
    if {"tipo_cita"} & keys:
        return "T3_STANCE_EVAL"
    return "UNKNOWN_SCHEMA:" + ",".join(sorted(keys))


def prompt_kind(user: str) -> str:
    u = norm(user)
    if "auditoría de citas" in u or "auditoria de citas" in u or "párrafo:" in u or "parrafo:" in u:
        return "T3_PROMPT"
    if "extracción jbi" in u or "extraccion jbi" in u or "sección de metodología" in u or "seccion de metodologia" in u:
        return "T2_PROMPT"
    if "módulo epistémico" in u or "modulo epistemico" in u or "analiza el siguiente resumen" in u:
        return "T1_PROMPT"
    return "UNKNOWN_PROMPT"


AREA_PAT = re.compile(r"en el área de ([a-z\-]+)", re.IGNORECASE)
AREA_PAT_PT = re.compile(r"área de ([a-z\-]+)", re.IGNORECASE)


def extract_area(user: str) -> str:
    m = AREA_PAT.search(user) or AREA_PAT_PT.search(user)
    return m.group(1).strip().lower() if m else ""


# ---------------------------------------------------------------- grounding
STOP = set("""
de la el los las un una unos unas y o en del al que se su sus con por para como
the of and to in a an for with on at is are be this that it its
da do das dos e ou em no na nos nas que se seu sua com por para como
articulos articulos científicos documentos indexados area área revisión revision
""".split())


def content_tokens(text: str) -> set[str]:
    toks = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}", norm(text))
    return {t for t in toks if t not in STOP}


def grounding_ratio(field_value: str, source: str) -> float:
    if not field_value or not source:
        return 0.0
    if norm(field_value).startswith("no especificado"):
        return 1.0  # declarar ausencia es correcto, no se penaliza
    toks = content_tokens(field_value)
    if not toks:
        return 0.0
    src = set(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}", norm(source)))
    return round(len(toks & src) / len(toks), 3)


def classify_t2_input(methods_text: str) -> str:
    """R5: el insumo de T2 debe ser metodologia, no bibliografia ni tablas ni rankings."""
    cuerpo = (methods_text or "").strip()
    if not cuerpo:
        return "NO_METODOLOGIA_VACIA"
    words = max(len(cuerpo.split()), 1)
    n_refs = len(REFERENCE_MARKERS.findall(cuerpo))
    n_ranks = len(JOURNAL_RANKING_MARKERS.findall(cuerpo))
    ref_por_100 = n_refs / words * 100
    inicio = norm(cuerpo[:250])
    marker_inicio = any(k in inicio for k in METHOD_MARKERS)
    marker_global = any(k in norm(cuerpo) for k in METHOD_MARKERS)
    if n_ranks >= 3:
        return "NO_METODOLOGIA_JOURNAL_RANKING"
    if ref_por_100 >= 1.5 and not marker_inicio:
        return "NO_METODOLOGIA_REFERENCE_LIST"
    if not marker_global:
        return "NO_METODOLOGIA_SIN_MARCADORES"
    if not marker_inicio:
        return "METODOLOGIA_DUDOSA_INICIO"
    if words < 60:
        return "METODOLOGIA_MUY_CORTA"
    return "METODOLOGIA_OK"


# ---------------------------------------------------------------- contradiccion
def label_mentioned_in_thought(thought: str, labels: list[str]) -> tuple[str, list[str]]:
    """Devuelve (veredicto, etiquetas aludidas) buscando los nombres en el pensamiento."""
    th = norm(thought)
    found = [lab for lab in labels if norm(lab) in th]
    if len(found) == 1:
        return "MENCION_UNICA", found
    if len(found) > 1:
        return "MENCION_MULTIPLE", found
    return "SIN_MENCION", []


# ---------------------------------------------------------------- auditoria
def auditar() -> tuple[list[dict], dict]:
    rows: list[dict] = []
    with open(DATASET_PATH, "r", encoding="utf-8") as fh:
        raw_lines = [ln for ln in fh.read().splitlines() if ln.strip()]

    for idx, line in enumerate(raw_lines, 1):
        obj = json.loads(line)
        msgs = {m.get("role"): m.get("content", "") for m in obj.get("messages", [])}
        system, user, target = msgs.get("system", ""), msgs.get("user", ""), msgs.get("assistant", "")

        tjson = extract_json_block(target)
        schema = schema_of(tjson)
        pkind = prompt_kind(user)
        area = extract_area(user)
        thought = extract_thought(target)

        row = {
            "idx": idx,
            "prompt_kind": pkind,
            "target_schema": schema,
            "mismatch_tarea": "NA",
            "area_en_prompt": area,
            "idioma_insumo": detect_language(user),
            "idioma_target": detect_language(target),
            "target_chars": len(target),
            "insumo_chars": len(user),
            "tiene_pensamiento": "SI" if thought else "NO",
            "echo_ratio": echo_ratio(target, user),
            "etiqueta_canonica": "",
            "etiqueta_valida": "",
            "contradiccion_pensamiento": "",
            "t2_tipo_insumo": "",
            "pcc_grounding_poblacion": "",
            "pcc_grounding_concepto": "",
            "pcc_grounding_contexto": "",
            "flags_degeneracion": "",
        }

        # --- etiqueta principal segun esquema
        if schema == "T1_ROLE":
            lab = str(tjson.get("rol_metodologico", ""))
            row["etiqueta_canonica"] = ROLES_MAP.get(norm(lab), "NO_MAPEABLE:" + lab)
            row["etiqueta_valida"] = "SI" if lab in ROLES_LEGACY else "NO"
            verdict, found = label_mentioned_in_thought(thought, TRADICIONES)
            etiqueta_trad = str(tjson.get("tradicion_epistemica", ""))
            if verdict == "MENCION_UNICA":
                declarada = found[0]
                row["contradiccion_pensamiento"] = (
                    "COINCIDE" if norm(declarada) == norm(etiqueta_trad) else "CONTRADICE"
                )
            else:
                row["contradiccion_pensamiento"] = verdict
        elif schema == "T2_PCC":
            row["etiqueta_valida"] = "SI" if tjson.get("concepto") else "NO"
        elif schema in ("T3_STANCE_LEGACY", "T3_STANCE_EVAL"):
            key = "tipo_relacion" if schema == "T3_STANCE_LEGACY" else "tipo_cita"
            lab = str(tjson.get(key, ""))
            row["etiqueta_canonica"] = lab
            row["etiqueta_valida"] = "SI" if any(norm(lab) == norm(s) for s in STANCES) else "NO"
            verdict, found = label_mentioned_in_thought(thought, STANCES)
            if verdict == "MENCION_UNICA":
                row["contradiccion_pensamiento"] = (
                    "COINCIDE" if norm(found[0]) == norm(lab) else "CONTRADICE"
                )
            else:
                row["contradiccion_pensamiento"] = verdict
        else:
            row["etiqueta_valida"] = "NO"

        # --- R2: mismatch solo cuando ambos lados son conocidos y difieren
        esperado = {"T1_PROMPT": {"T1_ROLE", "NO_JSON"}, "T2_PROMPT": {"T2_PCC", "NO_JSON"},
                    "T3_PROMPT": {"T3_STANCE_LEGACY", "T3_STANCE_EVAL", "NO_JSON"}}.get(pkind)
        if esperado is None or schema.startswith("UNKNOWN_SCHEMA"):
            row["mismatch_tarea"] = "INDETERMINADO"
        elif schema in esperado:
            row["mismatch_tarea"] = "NO"
        else:
            row["mismatch_tarea"] = "SI"

        # --- R5/R6: solo para T2
        if schema == "T2_PCC":
            m_body = re.search(r"METODOLOG[ÍI]A:\s*(.*)", user, re.DOTALL | re.IGNORECASE)
            metodo = m_body.group(1) if m_body else user
            row["t2_tipo_insumo"] = classify_t2_input(metodo)
            for campo in ("poblacion", "concepto", "contexto"):
                val = str(tjson.get(campo, "") or "")
                row["pcc_grounding_" + campo] = grounding_ratio(val, metodo)

        # --- R4: degeneraciones sobre target y pensamiento
        flags = find_degenerations(target)
        if row["echo_ratio"] >= 0.6:
            flags.append("ECHO_INPUT")
        if row["mismatch_tarea"] == "SI":
            flags.append("MISMATCH_TAREA")
        row["flags_degeneracion"] = "|".join(flags) if flags else "OK"

        rows.append(row)

    resumen = construir_resumen(rows)
    return rows, resumen


def _tabla(counter: Counter, titulo: str) -> dict:
    return {"titulo": titulo, "total": sum(counter.values()), "distribucion": dict(counter.most_common())}


def construir_resumen(rows: list[dict]) -> dict:
    r = {}
    r["total_filas"] = len(rows)
    r["por_esquema_target"] = _tabla(Counter(x["target_schema"] for x in rows), "Esquema del target (R1)")
    r["por_prompt"] = _tabla(Counter(x["prompt_kind"] for x in rows), "Tipo de prompt")
    r["mismatch_tarea"] = _tabla(Counter(x["mismatch_tarea"] for x in rows), "R2 Mismatch prompt<->target")
    r["idioma"] = _tabla(Counter(x["idioma_insumo"] for x in rows), "R7 Idioma del insumo")
    r["flags"] = _tabla(Counter(x["flags_degeneracion"] for x in rows), "R4 Flags por fila")
    r["tiene_pensamiento"] = _tabla(Counter(x["tiene_pensamiento"] for x in rows), "Bloque <pensamiento> presente")
    r["etiqueta_valida"] = _tabla(Counter(x["etiqueta_valida"] for x in rows), "Etiqueta dentro de taxonomia")

    t1 = [x for x in rows if x["target_schema"] == "T1_ROLE"]
    t2 = [x for x in rows if x["target_schema"] == "T2_PCC"]
    t3 = [x for x in rows if x["target_schema"].startswith("T3")]

    r["T1"] = {
        "n": len(t1),
        "roles": dict(Counter(x["etiqueta_canonica"] for x in t1).most_common()),
        "contradiccion_pensamiento": dict(Counter(x["contradiccion_pensamiento"] for x in t1).most_common()),
        "area_en_prompt": dict(Counter(x["area_en_prompt"] for x in t1).most_common()),
    }
    r["T2"] = {
        "n": len(t2),
        "tipo_insumo": dict(Counter(x["t2_tipo_insumo"] for x in t2).most_common()),
        "grounding_promedio": {
            campo: round(sum(float(x["pcc_grounding_" + campo]) for x in t2) / len(t2), 3) if t2 else 0.0
            for campo in ("poblacion", "concepto", "contexto")
        },
    }
    r["T3"] = {
        "n": len(t3),
        "etiquetas": dict(Counter(x["etiqueta_canonica"] for x in t3).most_common()),
        "contradiccion_pensamiento": dict(Counter(x["contradiccion_pensamiento"] for x in t3).most_common()),
    }

    # asociacion area -> etiqueta (atajo lexico)
    if t1:
        por_area = defaultdict(Counter)
        for x in t1:
            por_area[x["area_en_prompt"] or "(sin area)"][x["etiqueta_canonica"]] += 1
        r["T1"]["area_a_etiqueta"] = {k: dict(v.most_common()) for k, v in por_area.items()}

    r["echo_ratio_media"] = round(sum(float(x["echo_ratio"]) for x in rows) / len(rows), 3) if rows else 0.0
    return r


def main() -> None:
    rows, resumen = auditar()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    campos = list(rows[0].keys())
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerows(rows)

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(resumen, fh, ensure_ascii=False, indent=2)

    print("=" * 78)
    print("AUDITOR FORENSE DEL DATASET — GATE 1 (Fase 1)")
    print(f"Insumo: {DATASET_PATH.name}  |  Filas: {resumen['total_filas']}")
    print("=" * 78)
    for bloque in ("por_esquema_target", "por_prompt", "mismatch_tarea", "idioma", "flags", "etiqueta_valida", "tiene_pensamiento"):
        b = resumen[bloque]
        print(f"\n{b['titulo']} (total {b['total']}):")
        for k, v in b["distribucion"].items():
            print(f"    {v:3d}  {k}")
    print("\n--- T1 (clasificacion de rol) ---")
    print(f"  n = {resumen['T1']['n']}")
    print(f"  roles: {resumen['T1']['roles']}")
    print(f"  pensamiento vs etiqueta: {resumen['T1']['contradiccion_pensamiento']}")
    print(f"  area en el prompt: {resumen['T1']['area_en_prompt']}")
    print("\n--- T2 (extraccion PCC) ---")
    print(f"  n = {resumen['T2']['n']}")
    print(f"  tipo de insumo: {resumen['T2']['tipo_insumo']}")
    print(f"  grounding promedio: {resumen['T2']['grounding_promedio']}")
    print("\n--- T3 (postura de citas) ---")
    print(f"  n = {resumen['T3']['n']}")
    print(f"  etiquetas: {resumen['T3']['etiquetas']}")
    print(f"  pensamiento vs etiqueta: {resumen['T3']['contradiccion_pensamiento']}")
    print(f"\necho_ratio medio (target copiado del insumo): {resumen['echo_ratio_media']}")
    print(f"\nCSV  : {OUT_CSV}")
    print(f"JSON : {OUT_JSON}")
    print("=" * 78)


if __name__ == "__main__":
    main()
