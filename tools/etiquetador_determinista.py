"""Etiquetador determinista de stance (Fase 3 / Gate 2) — Thinkuy.

SIN modelos de lenguaje. Etiqueta cada contexto de citacion en TRES EJES ortogonales:

    A - Postura    : SUPPORT | CONFLICT | NEUTRAL
    B - Certeza    : STRONG | MODERATE | WEAK            (solo si hay marcador)
    C - Funcion    : REPORT | METHOD_ADOPTION | GAP | CONCESSION_REDEFINITION | OWN_CLAIM

Reglas duras:
  * Lista CERRADA de marcadores en ES + PT + EN.
  * Si no hay marcador, o si hay marcadores de ejes opuestos, la fila NO se adivina:
    se marca `AMBIGUO` y va a la cola de arbitraje humano.
  * El agente (propio vs. tercero) se detecta por referentes explicitos.

Salidas:
    data/dataset_v4/candidatos_stance.jsonl     — filas asignadas por regla
    data/dataset_v4/cola_ambiguo.jsonl          — filas que requieren arbitraje
    data/dataset_v4/diagnostico_stance.json     — distribuciones crudas
    data/dataset_v4/control_36.tsv              — muestra de control humano 12 ES/12 PT/12 EN
    data/dataset_v4/control_36.md               — version legible para anotar

USO:
    python tools/etiquetador_determinista.py [--max-por-articulo 15]
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.radar.text_extractor import (  # noqa: E402
    extract_citation_contexts,
    extract_numeric_citation_contexts,
    parse_reference_entry,
)

CORPUS_V2 = PROJECT_ROOT / "data" / "corpus_v2"
OUT_DIR = PROJECT_ROOT / "data" / "dataset_v4"


def norm(t: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


# =========================================================================
# LISTAS CERRADAS DE MARCADORES (ES / PT / EN)
# =========================================================================

A_MARKERS: dict[str, list[str]] = {
    "SUPPORT": [
        # ES
        "corrobora", "corroboran", "corroborado", "confirma", "confirman", "ratifica", "ratifican",
        "respalda", "respaldan", "apoya", "apoyan", "valida", "validan", "replica", "replican",
        "coincide con", "concuerda con", "converge con", "es consistente con", "en linea con",
        "en consonancia con", "tal como senalan", "refrenda",
        # PT
        "corrobora", "corroboram", "confirma", "confirmam", "ratifica", "ratificam", "respaldam",
        "apoiam", "validam", "replicam", "coincide com", "converge com", "consistente com",
        "em linha com", "em consonancia com",
        # EN
        "corroborate", "corroborates", "confirms", "confirm", "ratifies", "supports",
        "validates", "validate", "replicates", "converges with", "consistent with", "in line with",
        "agrees with", "in agreement with", "concurs",
        # `support` a secas casaba con sustantivos ("interpretative support", "social support",
        # "support network"), muy frecuentes en salud. Solo se acredita como verbo: seguido de
        # determinante o posesivo.
        "support the", "support this", "support these", "support that", "support our",
        "support their", "support its", "support his", "support her",
    ],
    "CONFLICT": [
        # ES
        "refuta", "refutan", "invalida", "invalidan", "desmiente", "contradice", "contradicen",
        "cuestiona", "cuestionan", "desafia", "desafian", "discrepa", "discrepan", "problematiza",
        "pone en duda", "difiere de", "difieren de", "a diferencia de", "en contraste con",
        "contrario a", "se opone a", "impugna", "desvirtua",
        # PT
        "refuta", "refutam", "invalida", "invalidam", "contradiz", "contradizem", "questiona",
        "questionam", "desafia", "desafiam", "discorda", "discordam", "problematiza", "diferem de",
        "diferentemente de", "em contraste com", "contrario a", "opoe-se a",
        # EN
        "refutes", "refute", "invalidates", "contradicts", "contradict", "challenges", "challenge",
        "questions", "questions the", "disagrees", "disagree", "diverges", "unlike", "in contrast to",
        "contrary to", "runs counter to", "challenges the",
    ],
    "CONCESSION": [
        # ES
        "si bien", "aunque", "a pesar de", "no obstante", "es cierto que", "reconocemos que",
        "admite que", "concede que", "soslaya", "matiza", "recontextualiza", "reformula",
        "delimita", "redefine", "acota", "extiende el marco", "complementa",
        # PT
        "embora", "ainda que", "apesar de", "nao obstante", "e certo que", "reconhecemos que",
        "admite que", "concede que", "recontextualiza", "reformula", "delimita", "redefine",
        "complementa",
        # EN
        "although", "though", "albeit", "while", "despite", "it is true that", "we acknowledge",
        "concedes", "recontextualizes", "reframes", "delimits", "redefines", "broadens",
        "extends the framework", "complements",
    ],
}

B_MARKERS: dict[str, list[str]] = {
    "STRONG": [
        "demuestra", "demuestran", "prueba", "prueban", "establece", "evidencia", "revela", "revelan",
        "taxativamente", "solidamente", "concluyentemente", "sin duda", "de manera concluyente",
        "demonstra", "demonstram", "comprova", "comprovam", "estabelece", "evidencia", "revela",
        "demonstrates", "demonstrate", "proves", "establishes", "clearly", "conclusively", "strongly",
    ],
    "MODERATE": [
        "indica", "indican", "sugiere", "sugieren", "muestra", "muestran", "senala", "senalan",
        "apunta", "apuntan", "sostiene", "sostienen", "plantea", "plantean", "refleja",
        "indica", "indicam", "sugere", "sugerem", "mostra", "mostram", "aponta", "apontam",
        "sustenta", "sustentam",
        "indicates", "indicate", "suggests", "suggest", "shows", "show", "points to", "notes",
        "argues", "maintains",
    ],
    "WEAK": [
        "podria", "podrian", "parece", "parecen", "tiende a", "tienden a", "posiblemente",
        "quizas", "tal vez", "en cierta medida", "debilmente",
        "poderia", "poderiam", "parece", "parecem", "tende a", "tendem a", "possivelmente",
        "talvez", "em certa medida",
        "might", "may", "appears", "appear", "seems", "seem", "tends to", "tend to", "possibly",
        "somewhat", "weakly",
    ],
}

C_MARKERS: dict[str, list[str]] = {
    "GAP": [
        # Marcadores INEQUÍVOCOS de vacío: se acreditan sin condición adicional.
        "no existen estudios", "no hay estudios", "vacio de conocimiento", "se desconoce",
        "poco explorado", "escasamente estudiado", "escasez de estudios",
        "nao ha estudos", "pouco explorado",
        "little is known", "remains unknown", "has not been studied", "understudied",
        "research gap", "few studies", "scarce research", "scarce evidence",
    ],
    "METHOD_ADOPTION": [
        "utilizando el metodo", "utilizando la metodologia", "siguiendo a", "siguiendo el protocolo",
        "adaptando la escala", "adaptando el instrumento", "segun el protocolo", "con el instrumento de",
        "se adopto", "tomando como referencia", "basado en el protocolo", "con base en el metodo",
        "utilizando o metodo", "seguindo", "adaptando", "com base no protocolo", "adotou-se",
        "using the method", "following the protocol", "adapted from", "based on the method",
        "using the instrument", "adopted the",
    ],
    "CONCESSION_REDEFINITION": [],
    "REPORT": [
        "describe", "describen", "reporta", "reportan", "analiza", "analizan", "examina", "examinan",
        "explora", "exploran", "investiga", "investigan", "observa", "observan", "presenta",
        "presentan", "aborda", "abordan", "documenta", "documentan", "caracteriza", "mapea",
        "descreve", "descrevem", "relata", "analisa", "analisam", "examina", "explora",
        "investiga", "apresenta", "aborda", "documenta", "caracteriza", "mapeia",
        "describes", "reports", "analyses", "analyzes", "examines", "explores", "investigates",
        "observes", "presents", "addresses", "documents", "characterizes", "maps",
    ],
    "OWN_CLAIM": [],
}

OWN_REFERENTS = [
    "nuestro", "nuestra", "nuestros", "nuestras", "este estudio", "este trabajo", "esta revision",
    "esta investigacion", "este articulo", "nuestro analisis", "los resultados de este",
    "se concluye que", "se encontro que", "se identifico que",
    "nossos", "nossas", "este estudo", "este trabalho", "esta revisao", "esta pesquisa",
    "nosso", "nossa", "os resultados deste",
    "our ", "we ", "we found", "this study", "this paper", "this review", "this article",
    "we propose", "we argue", "we identified",
]

THIRD_PARTY_REFERENTS = [
    "el estudio de", "los autores", "los trabajos de", "la literatura", "segun ",
    "o estudo de", "os autores", "a literatura", "segundo ",
    "the study by", "the authors", "the literature", "according to",
]

YEAR_RE = re.compile(r"\((?:19|20)\d{2}[a-z]?\)|(?:19|20)\d{2}[a-z]?\b")

# Atribucion explicita: Autor (Ano) / Autor et al. (Ano) / Autor, Ano  (sobre texto ORIGINAL)
AUTOR_ANO_RE = re.compile(
    r"\b[A-Za-zÁÉÍÓÚÑÜáéíóúñü][A-Za-zÁÉÍÓÚÑÜáéíóúñü\-]{2,}"
    r"\s*(?:et\s+al\.?|y\s+[A-Za-zÁÉÍÓÚÑÜáéíóúñü\-]{2,}|e\s+[A-Za-zÁÉÍÓÚÑÜáéíóúñü\-]{2,}|and\s+[A-Za-zÁÉÍÓÚÑÜáéíóúñü\-]{2,}|&\s*[A-Za-zÁÉÍÓÚÑÜáéíóúñü\-]{2,})?"
    r"\s*[,\s]*\(\s*(?:19|20)\d{2}[a-z]?\s*\)"
)
AUTOR_COMA_ANO_RE = re.compile(
    r"\b[A-ZÁÉÍÓÚÑÜ][A-Za-zÁÉÍÓÚÑÜáéíóúñü\-]{2,}\s*(?:et\s+al\.?)?\s*,\s*(?:19|20)\d{2}[a-z]?\b"
)
# Cita numerica [12], [3-5], (12) — excluyendo anios de 4 digitos
NUM_CITE_RE = re.compile(r"[\(\[]\s*\d{1,3}(?:\s*[-,]\s*\d{1,3})*\s*[\)\]]")

# Verbos de reporte no factivos (Thompson & Ye): atribuir sin evaluar
REPORT_VERBS_ES = [
    "estudio", "estudia", "estudiaron", "analizo", "analizaron", "exploro", "exploraron",
    "examino", "examinaron", "describio", "describieron", "reporto", "reportaron",
    "investigo", "investigaron", "observo", "observaron", "presento", "presentaron",
    "abordo", "abordaron", "documento", "documentaron", "evidencio", "identifico",
]
REPORT_VERBS_PT = [
    "estudou", "estudaram", "analisou", "analisaram", "explorou", "exploraram", "examinou",
    "examinaram", "descreveu", "descreveram", "relatou", "relataram", "investigou",
    "investigaram", "observou", "observaram", "apresentou", "apresentaram", "abordou",
]
REPORT_VERBS_EN = [
    "studied", "study", "studies", "analyzed", "analysed", "explored", "examined", "described",
    "reported", "investigated", "observed", "presented", "addressed", "documented", "found",
    "showed", "shows",
]
REPORT_VERBS_RE = re.compile(
    r"(?<![a-z0-9])(" + "|".join(norm(v) for v in REPORT_VERBS_ES + REPORT_VERBS_PT + REPORT_VERBS_EN) + r")(?![a-z0-9])"
)


def _compile(phrases: list[str]) -> list[tuple[str, re.Pattern]]:
    out = []
    for p in phrases:
        np_ = norm(p)
        if not np_:
            continue
        out.append((p, re.compile(r"(?<![a-z0-9])" + re.escape(np_) + r"(?![a-z0-9])")))
    return out


COMPILED = {
    "A": {k: _compile(v) for k, v in A_MARKERS.items()},
    "B": {k: _compile(v) for k, v in B_MARKERS.items()},
    "C": {k: _compile(v) for k, v in C_MARKERS.items() if v},
}
CONCESSION_COMPILED = _compile(A_MARKERS["CONCESSION"])

# ── Vacío de conocimiento: marcadores GENÉRICOS con guardián de objeto epistémico ──────
# Corrección tras la demostración (Hito 32): `falta de`, `lack of` y `ausencia de` daban
# falsos positivos sobre objetos concretos —«falta de energía» (síntoma), «ausencia de
# HBsAg» (criterio de laboratorio), «lack of knowledge» (barrera listada)—. Solo cuentan
# si el objeto es epistémico: estudios, evidencia, literatura, datos, investigación…
GAP_GENERICOS = [
    "falta de", "ausencia de", "carece de", "carencia de", "escasez de",
    "no se encontro", "no se encontraron", "no se ha encontrado", "no se identifico",
    "escassez de", "carência de", "nao foram encontrados",
    "lack of", "absence of", "no evidence", "has not been", "insufficient evidence",
]

OBJETO_EPISTEMICO = [
    # ES
    "estudio", "investigacion", "evidencia", "literatura", "dato", "informacion", "conocimiento",
    "publicacion", "trabajo", "revision", "analisis", "ensayo", "articulo", "bibliografia",
    # PT
    "estudo", "pesquisa", "evidencia", "literatura", "dado", "informacao", "conhecimento",
    "publicacao", "revisao", "analise", "ensaio", "artigo",
    # EN
    "studies", "research", "evidence", "literature", "data", "information", "knowledge",
    "publications", "reviews", "trials", "findings", "papers", "articles",
]

GAP_GENERICOS_C = _compile(GAP_GENERICOS)


def gap_con_objeto_epistemico(texto_n: str, radio: int = 90) -> list[str]:
    """Devuelve los marcadores genéricos de vacío cuyo objeto próximo es epistémico."""
    validos: list[str] = []
    for original, patron in GAP_GENERICOS_C:
        m = patron.search(texto_n)
        if not m:
            continue
        ventana = texto_n[m.end(): m.end() + radio]
        if any(obj in ventana for obj in OBJETO_EPISTEMICO):
            validos.append(original)
    return validos


def detectar_marcadores(texto_n: str, eje: str) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for valor, patrones in COMPILED[eje].items():
        encontrados = [orig for orig, pat in patrones if pat.search(texto_n)]
        if encontrados:
            hits[valor] = encontrados
    return hits


def atribucion_explicita(oracion_raw: str) -> bool:
    """¿La oración atribuye explícitamente a una obra? (Autor-Año o cita numérica)."""
    s = oracion_raw or ""
    if AUTOR_ANO_RE.search(s) or AUTOR_COMA_ANO_RE.search(s):
        return True
    for m in NUM_CITE_RE.finditer(s):
        if not re.search(r"\d{4}", m.group(0)):  # un año no es una cita numérica
            return True
    return False


def detectar_agente(texto_n: str, oracion_raw: str) -> str:
    propio = any(norm(r) in texto_n for r in OWN_REFERENTS)
    tercero = (
        any(norm(r) in texto_n for r in THIRD_PARTY_REFERENTS)
        or atribucion_explicita(oracion_raw)
    )
    if propio and not tercero:
        return "PROPIO"
    if tercero and not propio:
        return "TERCERO"
    if propio and tercero:
        return "AMBOS"
    return "INDETERMINADO"


def ventana_de_cita(oracion: str, parrafo: str, autor_citado: str | None, radio: int = 300) -> str:
    """Ventana de análisis = LA ORACIÓN DE LA CITA.

    Corrección tras el Gate 2: la ventana de ±300 caracteres capturaba marcadores de
    oraciones vecinas y producía `SUPPORT`/`CONFLICT`/`CONCESSION` falsos. Solo se recurre
    al párrafo cuando la oración es demasiado corta para juzgar.
    """
    parrafo = parrafo or ""
    oracion = (oracion or "").strip()
    if len(oracion) >= 40:
        return oracion[:600]
    apellido = ""
    if autor_citado:
        apellido = norm(str(autor_citado).split(",")[0].split()[-1]) if str(autor_citado).strip() else ""
    if apellido and len(apellido) >= 4:
        p_n = norm(parrafo)
        i = p_n.find(apellido)
        if i != -1:
            ini = max(0, i - radio)
            fin = min(len(parrafo), i + radio)
            return parrafo[ini:fin]
    return oracion if oracion else parrafo[:600]


SEPARADOR_CLAUSULA = re.compile(
    r"(?<=[;.!?])\s+|"
    r",\s*(?=(?:pero|sin embargo|aunque|no obstante|mientras|mas|por[eé]m|contudo|entretanto|"
    r"but|however|although|though|whereas|yet)\b)",
    re.IGNORECASE,
)


def en_clausulas(texto: str) -> list[str]:
    """Divide el texto en cláusulas: unidad mínima para adjudicar un marcador a su agente."""
    partes = [p.strip() for p in SEPARADOR_CLAUSULA.split(texto or "") if p and p.strip()]
    return partes or [(texto or "").strip()]


def _fusionar(destino: dict, nuevo: dict) -> None:
    for k, v in (nuevo or {}).items():
        destino.setdefault(k, [])
        for x in v:
            if x not in destino[k]:
                destino[k].append(x)


PROHIBIDO_INICIO = re.compile(
    r"^(quadro|tabla|table|figura|figure|chart|imagen|gr[aá]fico)\s*\d|"
    r"^\d+\s*(https?://|doi)|^https?://|^doi:?\s*10\.",
    re.IGNORECASE,
)


def oracion_util(s: str) -> tuple[bool, str]:
    """Filtro de calidad del contexto (defecto detectado por el IP: oraciones basura).

    Devuelve (util, motivo_de_rechazo). Rechaza encabezados, líneas de DOI, fragmentos de
    tabla y oraciones demasiado cortas o con exceso de cifras.
    """
    t = (s or "").strip()
    if len(t) < 60:
        return False, "ORACION_MUY_CORTA"
    palabras = t.split()
    if len(palabras) < 8:
        return False, "MENOS_DE_8_PALABRAS"
    letras = sum(c.isalpha() for c in t)
    ratio_letras = letras / max(len(t), 1)
    if ratio_letras < 0.62:
        return False, "PROPORCION_DE_LETRAS_BAJA"
    if PROHIBIDO_INICIO.match(t):
        return False, "ENCABEZADO_O_DOI"
    # Un DOI o URL dentro de los primeros 80 caracteres indica contaminación de encabezado
    # (caso detectado en la muestra del IP: "8/17 Interface (Botucatu) https://doi.org/...").
    if re.search(r"https?://|doi\.org|dx\.doi", t[:80], re.IGNORECASE):
        return False, "URL_O_DOI_INTERNO"
    # Restos de maquetación: barras de paginación, ISSN, marcas de revista
    if re.search(r"\bISSN\b|e-ISSN|Continua>>|^\d+\s*/\s*\d+\s+[A-Z]", t, re.IGNORECASE):
        return False, "RESTO_DE_MAQUETACION"
    digitos = sum(c.isdigit() for c in t)
    if digitos / max(len(t), 1) > 0.22:
        return False, "EXCESO_DE_CIFRAS"
    if t.count("[") + t.count("]") > 12:
        return False, "LISTA_DE_REFERENCIAS_EN_LA_ORACION"
    if not re.search(r"[a-záéíóúñçãõ]{4,}\s+[a-záéíóúñçãõ]{3,}", t.lower()):
        return False, "SIN_PROSA"
    return True, ""


def etiquetar(oracion: str, parrafo: str, seccion: str, autor_citado: str | None = None) -> dict:
    """Etiqueta los 3 ejes. Nunca adivina: lo indecidible sale como AMBIGUO.

    Adjudicación por agente (corrección tras el Gate 2): cada marcador se acredita al
    AGENTE DE SU CLÁUSULA. Si el sujeto es la obra citada —"García cuestiona el modelo
    de Lee"— el verbo describe lo que hizo García: es un REPORT del que cita, no su
    CONFLICT. Antes, la regla aplicaba el marcador a la ventana entera y sobre-atribuía
    postura (15 de sus 20 SUPPORT/CONFLICT eran NEUTRAL para el anotador humano).
    """
    ventana = ventana_de_cita(oracion, parrafo, autor_citado)
    base = norm(ventana)

    hitA: dict = {}
    hitB: dict = {}
    hitC: dict = {}
    hitConc: list = []
    b_en_tercero = 0
    b_en_propio = 0

    for clausula in en_clausulas(ventana):
        cn = norm(clausula)
        ag = detectar_agente(cn, clausula)
        marcA = detectar_marcadores(cn, "A")
        marcB = detectar_marcadores(cn, "B")
        marcC = detectar_marcadores(cn, "C")
        conc = [o for o, p in CONCESSION_COMPILED if p.search(cn)]

        # La postura del que ESCRIBE solo se acredita si la cláusula no la protagoniza
        # la obra citada.
        if ag != "TERCERO":
            _fusionar(hitA, marcA)
        if marcB:
            if ag == "TERCERO":
                b_en_tercero += 1
            else:
                b_en_propio += 1
        _fusionar(hitB, marcB)
        _fusionar(hitC, marcC)
        # Vacío: los marcadores genéricos solo cuentan con objeto epistémico próximo
        gap_gen = gap_con_objeto_epistemico(cn)
        if gap_gen:
            _fusionar(hitC, {"GAP": gap_gen})
        hitConc += conc

    hay_verbo_reporte = bool(REPORT_VERBS_RE.search(base))
    atrib = atribucion_explicita(oracion or "")
    agente = detectar_agente(base, oracion or "")

    motivos: list[str] = []
    # Si toda la carga de certeza vive en cláusulas de tercero, el que cita no evalúa
    # fuerza alguna: es un reporte.
    if b_en_tercero and not b_en_propio:
        hitB = {}
        motivos.append("certeza en cláusula de tercero: se degrada a NO_DECLARADA")

    sin_marcadores = not (hitA or hitB or hitC or hitConc or hay_verbo_reporte)

    # ── Regla determinista de reporte neutro ──
    # Una atribucion EXPLICITA (Autor-Año o cita numérica) sin carga evaluativa
    # es, por definicion de la taxonomia, un acto de reporte: no se adivina, se constata.
    if sin_marcadores and atrib:
        return {
            "eje_A": "NEUTRAL",
            "eje_B": "NO_DECLARADA",
            "eje_C": "REPORT",
            "agente": agente if agente != "INDETERMINADO" else "TERCERO",
            "veredicto": "ASIGNADO",
            "marcadores_A": {},
            "marcadores_B": {},
            "marcadores_C": {"REPORT": ["atribucion_explicita_sin_marcador"]},
            "marcadores_concesion": [],
            "motivos": ["atribucion explicita sin marcador evaluativo -> REPORT"],
        }

    # ── Eje A ──
    soporte, conflicto = "SUPPORT" in hitA, "CONFLICT" in hitA
    if soporte and conflicto:
        ejeA = "AMBIGUO"
        motivos.append("marcadores de soporte y conflicto coexisten")
    elif soporte:
        ejeA = "SUPPORT"
    elif conflicto:
        ejeA = "CONFLICT"
    else:
        ejeA = "NEUTRAL"
        if hitConc:
            motivos.append("marcador concesivo: postura no comprometida")

    # ── Eje B ──
    if "STRONG" in hitB:
        ejeB = "STRONG"
    elif "WEAK" in hitB:
        ejeB = "WEAK"
    elif "MODERATE" in hitB:
        ejeB = "MODERATE"
    else:
        ejeB = "NO_DECLARADA"

    # ── Eje C (prioridad: GAP > METHOD > CONCESION > OWN > REPORT) ──
    if "GAP" in hitC:
        ejeC = "GAP"
    elif "METHOD_ADOPTION" in hitC:
        ejeC = "METHOD_ADOPTION"
    elif hitConc:
        ejeC = "CONCESSION_REDEFINITION"
    elif agente == "PROPIO" and ejeB in ("STRONG", "MODERATE") and "REPORT" not in hitC:
        ejeC = "OWN_CLAIM"
    elif "REPORT" in hitC or hay_verbo_reporte or atrib:
        ejeC = "REPORT"
    else:
        ejeC = "AMBIGUO"
        motivos.append("sin marcador de funcion y sin atribucion explicita")

    # ── Veredicto ──
    ambiguo = ejeA == "AMBIGUO" or ejeC == "AMBIGUO"
    if sin_marcadores:
        ambiguo = True
        motivos.append("ningun marcador de la lista cerrada y sin atribucion")
    if agente == "AMBOS":
        motivos.append("agente propio y tercero coexisten (revisar)")
    if seccion == "references":
        ambiguo = True
        motivos.append("contexto dentro de la bibliografia")

    return {
        "eje_A": ejeA if not ambiguo or ejeA != "AMBIGUO" else "AMBIGUO",
        "eje_B": ejeB,
        "eje_C": ejeC,
        "agente": agente,
        "veredicto": "AMBIGUO" if ambiguo else "ASIGNADO",
        "marcadores_A": {k: v for k, v in hitA.items()},
        "marcadores_B": {k: v for k, v in hitB.items()},
        "marcadores_C": {k: v for k, v in hitC.items()},
        "marcadores_concesion": hitConc,
        "motivos": motivos,
    }


# =========================================================================
# RECORRIDO DEL CORPUS
# =========================================================================

def cargar_unicos() -> list[dict]:
    p = CORPUS_V2 / "inventario_unicos.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return data["unicos"]


def procesar(max_por_articulo: int) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Etiqueta TODOS los contextos hallados. El tope solo acota casos patológicos."""
    unicos = cargar_unicos()
    filas_senal: list[dict] = []
    filas_reporte: list[dict] = []
    ambiguos: list[dict] = []
    sin_citas: list[str] = []
    rechazadas: dict[str, int] = {}

    for rec in unicos:
        if not rec["usabilidad"]["T3"]:
            continue
        sect = rec.get("sections") or {}
        cuerpo = "\n\n".join(v for k, v in sect.items() if k not in ("references",) and v)
        if len(cuerpo) < 4000:
            continue
        refs_parseadas = []
        for r in (rec.get("references") or [])[:200]:
            pr = parse_reference_entry(r)
            if pr and (pr.get("author") or pr.get("doi")):
                refs_parseadas.append(pr)
        vistos: set[str] = set()
        contextos: list[dict] = []
        for pr in refs_parseadas[:60]:
            for ctx in extract_citation_contexts(
                cuerpo, cited_doi=pr.get("doi") or "", cited_author=pr.get("author"), cited_year=pr.get("year")
            ):
                key = norm(ctx.get("sentence", ""))[:70]
                if not key or key in vistos:
                    continue
                vistos.add(key)
                contextos.append({"ctx": ctx, "ref": pr})

        # Via numerica: resuelve [n] -> n-esima referencia (articulos sin cita por apellido)
        for ctx in extract_numeric_citation_contexts(cuerpo, rec.get("references") or []):
            key = norm(ctx.get("sentence", ""))[:70]
            if not key or key in vistos:
                continue
            vistos.add(key)
            contextos.append({"ctx": ctx, "ref": {
                "author": ctx.get("cited_author"),
                "year": ctx.get("cited_year"),
                "doi": ctx.get("cited_doi"),
            }})

        if not contextos:
            sin_citas.append(rec["ruta_relativa"])
            continue
        for item in contextos[:max_por_articulo]:
            ctx, pr = item["ctx"], item["ref"]
            oracion = ctx.get("sentence", "")
            util, motivo = oracion_util(oracion)
            if not util:
                rechazadas[motivo] = rechazadas.get(motivo, 0) + 1
                continue
            lab = etiquetar(oracion, ctx.get("paragraph", ""), ctx.get("section", "body"),
                            autor_citado=pr.get("author"))
            fila = {
                "lote": rec.get("lote"),
                "doi_filename": rec["doi_filename"],
                "area": rec["area"],
                "idioma": rec["idioma"],
                "seccion": ctx.get("section", "body"),
                "autor_citado": pr.get("author"),
                "ano_citado": pr.get("year"),
                "doi_citado": pr.get("doi"),
                "oracion": ctx.get("sentence", ""),
                "parrafo": (ctx.get("paragraph", "") or "")[:1200],
                **lab,
            }
            if lab["veredicto"] == "AMBIGUO":
                ambiguos.append(fila)
            elif lab["eje_C"] == "REPORT" and lab["eje_A"] == "NEUTRAL" and lab["eje_B"] == "NO_DECLARADA":
                filas_reporte.append(fila)
            else:
                filas_senal.append(fila)

    diag = {
        "articulos_T3_evaluados": sum(1 for r in unicos if r["usabilidad"]["T3"]),
        "articulos_sin_contextos": len(sin_citas),
        "filas_senal": len(filas_senal),
        "filas_reporte": len(filas_reporte),
        "filas_ambiguas": len(ambiguos),
        "contextos_rechazados_por_calidad": rechazadas,
        "senal_por_idioma": dict(Counter(r["idioma"] for r in filas_senal).most_common()),
        "reporte_por_idioma": dict(Counter(r["idioma"] for r in filas_reporte).most_common()),
        "ambiguas_por_idioma": dict(Counter(r["idioma"] for r in ambiguos).most_common()),
        "eje_A_senal": dict(Counter(r["eje_A"] for r in filas_senal).most_common()),
        "eje_B_senal": dict(Counter(r["eje_B"] for r in filas_senal).most_common()),
        "eje_C_senal": dict(Counter(r["eje_C"] for r in filas_senal).most_common()),
        "eje_A_reporte": dict(Counter(r["eje_A"] for r in filas_reporte).most_common()),
        "agente_senal": dict(Counter(r["agente"] for r in filas_senal).most_common()),
        "motivos_ambiguo": dict(Counter(m for r in ambiguos for m in r["motivos"]).most_common()),
        "sin_citas": sin_citas[:20],
    }
    return filas_senal, filas_reporte, ambiguos, diag


def balancear(senal: list[dict], reporte: list[dict], cuota_reporte: float = 0.35, semilla: int = 3407) -> list[dict]:
    """Muestrea el reporte neutro para que no supere `cuota_reporte` del dataset final.

    Regla del protocolo: el modelo debe ver suficientes marcadores como para aprenderlos;
    si el 90 % de las filas son reporte neutro, el colapso de modo es el resultado esperado.
    """
    if not senal:
        return list(reporte)
    objetivo = int(len(senal) * cuota_reporte / (1 - cuota_reporte))
    if len(reporte) <= objetivo:
        return senal + reporte
    rnd = random.Random(semilla)
    # muestreo estratificado por idioma para no romper el balance ES/PT/EN
    por_idioma: dict[str, list[dict]] = defaultdict(list)
    for r in reporte:
        por_idioma[r["idioma"]].append(r)
    cuota_idioma = {"ES": 0.45, "PT": 0.30, "EN": 0.25}
    seleccion: list[dict] = []
    for idioma, pool in por_idioma.items():
        n = int(objetivo * cuota_idioma.get(idioma, 0.25))
        seleccion += rnd.sample(pool, min(n, len(pool)))
    if len(seleccion) < objetivo:
        resto = [r for r in reporte if r not in seleccion]
        seleccion += rnd.sample(resto, min(objetivo - len(seleccion), len(resto)))
    return senal + seleccion


def construir_control(filas: list[dict], ambiguos: list[dict], por_idioma: int = 12, semilla: int = 3407) -> list[dict]:
    """Muestra de control estratificada por idioma Y por dificultad.

    Restricciones adicionales (defectos detectados por el IP en la primera muestra):
      * un solo caso por PÁRRAFO (antes salían PT-11 y PT-12 con el mismo contexto);
      * un solo caso por ARTÍCULO cuando hay alternativa (evita concentrar la muestra).
    """
    rnd = random.Random(semilla)
    muestra: list[dict] = []
    parrafos_usados: set[str] = set()
    articulos_usados: set[str] = set()

    def tomar(pool: list[dict], n: int) -> list[dict]:
        sel: list[dict] = []
        for r in pool:
            if len(sel) >= n:
                break
            ph = norm((r.get("parrafo") or "")[:160])
            art = r.get("doi_filename", "")
            if ph and ph in parrafos_usados:
                continue
            if art and art in articulos_usados and len(pool) > n:
                continue
            if ph:
                parrafos_usados.add(ph)
            if art:
                articulos_usados.add(art)
            sel.append(r)
        return sel

    for idioma in ("ES", "PT", "EN"):
        pool = [r for r in filas if r["idioma"] == idioma]
        amb = [r for r in ambiguos if r["idioma"] == idioma]

        conflicto = [r for r in pool if r["eje_A"] == "CONFLICT"]
        apoyo = [r for r in pool if r["eje_A"] == "SUPPORT"]
        funcion = [r for r in pool if r["eje_C"] in ("GAP", "METHOD_ADOPTION", "CONCESSION_REDEFINITION")]
        facil = [r for r in pool if r["eje_A"] == "NEUTRAL" and r["eje_C"] == "REPORT"]

        sel: list[dict] = []
        sel += tomar(conflicto, 3)
        sel += tomar(apoyo, 3)
        sel += tomar(funcion, 3)
        sel += tomar(amb, 2)
        faltan = por_idioma - len(sel)
        if faltan > 0:
            usados = {r.get("oracion") for r in sel}
            resto = [r for r in (facil + funcion + apoyo + conflicto + amb) if r.get("oracion") not in usados]
            sel += tomar(resto, faltan)

        for i, r in enumerate(sel, 1):
            copia = dict(r)
            copia["control_id"] = f"{idioma}-{i:02d}"
            muestra.append(copia)
    return muestra


def anadir_pesos(filas: list[dict]) -> dict:
    """Añade peso por clase para cada eje (inverso a la frecuencia, media 1, con tope 10).

    Alternativa honesta a duplicar filas: el desbalance se corrige ponderando la perdida
    o el muestreo, no inventando copias que favorecen la memorizacion.
    Las clases con menos de MIN_EJEMPLOS_POR_CLASE ejemplos se marcan como excluidas del
    target (no son aprendibles y su peso inverso seria patologico).
    """
    MIN_EJEMPLOS_POR_CLASE = 10
    TOPE_PESO = 10.0
    pesos: dict[str, dict[str, float]] = {}
    excluidas: dict[str, list[str]] = {}
    for eje in ("eje_A", "eje_B", "eje_C"):
        cuenta = Counter(r[eje] for r in filas)
        n = len(filas)
        k = len(cuenta)
        pesos[eje] = {v: round(min(n / (k * c), TOPE_PESO), 4) for v, c in cuenta.items()}
        excluidas[eje] = sorted([v for v, c in cuenta.items() if c < MIN_EJEMPLOS_POR_CLASE])
        for r in filas:
            r[f"peso_{eje.split('_')[1]}"] = pesos[eje][r[eje]]
            r[f"target_{eje.split('_')[1]}"] = "EXCLUIDA" if r[eje] in excluidas[eje] else "ENTRENABLE"
    return {"pesos": pesos, "clases_excluidas_del_target": excluidas, "min_ejemplos": MIN_EJEMPLOS_POR_CLASE,
            "tope_peso": TOPE_PESO}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-por-articulo", type=int, default=60)
    ap.add_argument("--cuota-reporte", type=float, default=0.35)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    senal, reporte, ambiguos, diag = procesar(args.max_por_articulo)
    balanceado = balancear(senal, reporte, args.cuota_reporte)
    pesos = anadir_pesos(balanceado)
    diag["pesos_por_clase"] = pesos
    diag["dataset_balanceado"] = {
        "n": len(balanceado),
        "por_idioma": dict(Counter(r["idioma"] for r in balanceado).most_common()),
        "eje_A": dict(Counter(r["eje_A"] for r in balanceado).most_common()),
        "eje_B": dict(Counter(r["eje_B"] for r in balanceado).most_common()),
        "eje_C": dict(Counter(r["eje_C"] for r in balanceado).most_common()),
        "cuota_reporte_aplicada": args.cuota_reporte,
    }

    for nombre, filas in (("candidatos_senal", senal), ("candidatos_reporte", reporte), ("cola_ambiguo", ambiguos),
                          ("dataset_balanceado", balanceado)):
        with open(OUT_DIR / f"{nombre}.jsonl", "w", encoding="utf-8") as fh:
            for r in filas:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(OUT_DIR / "diagnostico_stance.json", "w", encoding="utf-8") as fh:
        json.dump(diag, fh, ensure_ascii=False, indent=2)

    control = construir_control(senal + reporte, ambiguos)
    _flat = lambda t, n=None: (re.sub(r"\s+", " ", (t or "")).strip().replace("\t", " ")[:n] if n else re.sub(r"\s+", " ", (t or "")).strip().replace("\t", " "))
    with open(OUT_DIR / "control_36.tsv", "w", encoding="utf-8", newline="") as fh:
        fh.write("control_id\tidioma\toracion\tparrafo\tA_regla\tB_regla\tC_regla\tagente\tveredicto\tA_humano\tB_humano\tC_humano\tnorma\n")
        for r in control:
            fh.write("\t".join([
                r["control_id"], r["idioma"],
                _flat(r["oracion"]),
                _flat(r["parrafo"], 900),
                r["eje_A"], r["eje_B"], r["eje_C"], r["agente"], r["veredicto"], "", "", "", "",
            ]) + "\n")

    with open(OUT_DIR / "control_36.md", "w", encoding="utf-8") as fh:
        fh.write("# Muestra de control humano (36 casos) — Gate 2\n\n")
        fh.write("Anota **A**, **B** y **C** en cada caso. Si no puedes decidir, escribe `AMBIGUO`: esa respuesta también es un dato.\n\n")
        fh.write("- A (postura): `SUPPORT` | `CONFLICT` | `NEUTRAL`\n")
        fh.write("- B (certeza): `STRONG` | `MODERATE` | `WEAK` | `NO_DECLARADA`\n")
        fh.write("- C (función): `REPORT` | `METHOD_ADOPTION` | `GAP` | `CONCESSION_REDEFINITION` | `OWN_CLAIM`\n\n")
        for r in control:
            fh.write(f"## {r['control_id']} — {r['idioma']} — {r['area']}\n\n")
            fh.write(f"**Oración:** {r['oracion']}\n\n")
            fh.write(f"**Contexto:** {(r['parrafo'] or '')[:700]}\n\n")
            fh.write(f"**Regla propone:** A=`{r['eje_A']}` · B=`{r['eje_B']}` · C=`{r['eje_C']}` · agente=`{r['agente']}` · veredicto=`{r['veredicto']}`\n\n")
            fh.write("**Tu etiqueta:** A=`____` · B=`____` · C=`____` · nota: ____\n\n---\n\n")

    print("=" * 78)
    print("ETIQUETADOR DETERMINISTA DE STANCE — FASE 3")
    print("=" * 78)
    print(f"Articulos T3 evaluados : {diag['articulos_T3_evaluados']}")
    print(f"Articulos sin contextos: {diag['articulos_sin_contextos']}")
    print(f"Filas de SENAL (marcador) : {diag['filas_senal']}  {diag['senal_por_idioma']}")
    print(f"Filas de REPORTE neutro   : {diag['filas_reporte']}  {diag['reporte_por_idioma']}")
    print(f"Filas AMBIGUAS           : {diag['filas_ambiguas']}  {diag['ambiguas_por_idioma']}")
    print(f"\nEje A (senal): {diag['eje_A_senal']}")
    print(f"Eje B (senal): {diag['eje_B_senal']}")
    print(f"Eje C (senal): {diag['eje_C_senal']}")
    print(f"Agente (senal): {diag['agente_senal']}")
    print(f"\nDATASET BALANCEADO: {diag['dataset_balanceado']['n']} filas")
    print(f"  idioma: {diag['dataset_balanceado']['por_idioma']}")
    print(f"  A: {diag['dataset_balanceado']['eje_A']}")
    print(f"  B: {diag['dataset_balanceado']['eje_B']}")
    print(f"  C: {diag['dataset_balanceado']['eje_C']}")
    print(f"\nMotivos de ambiguedad: {diag['motivos_ambiguo']}")
    print("\nPESOS POR CLASE (inverso a la frecuencia, media 1) — usar en la perdida o el muestreo:")
    for eje, d in pesos["pesos"].items():
        print(f"    {eje}: {d}")
    print(f"\nClases EXCLUIDAS del target (< {pesos['min_ejemplos']} ejemplos): {pesos['clases_excluidas_del_target']}")
    print(f"\nControl humano: {len(control)} casos -> {OUT_DIR / 'control_36.md'}")
    print("=" * 78)


if __name__ == "__main__":
    main()
