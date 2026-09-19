"""Etiquetador determinista de la matriz JBI PCC (T2) — Fase 3b.

Extrae Poblacion / Concepto / Contexto / Diseno con guardian de grounding duro:

  * Todo campo es un SPAN VERBATIM de la fuente (subcadena literal), no una parafrasis.
  * Si el dato no consta, el campo se emite como
    "No especificado en la metodología" — NUNCA se inventa ni se rellena.
  * Guardas de negacion explicita y de relleno generico.

Cobertura trilingue ES/PT/EN. Cada campo declara su FUENTE, porque el "Concepto" de JBI
es la pregunta de investigacion y vive en el abstract/introduccion, no en la metodologia.

NO usa modelos de lenguaje.

USO:
    python tools/etiquetador_t2_pcc.py
SALIDAS:
    data/dataset_v4/t2_pcc.jsonl
    data/dataset_v4/diagnostico_t2.json
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORPUS_V2 = PROJECT_ROOT / "data" / "corpus_v2"
OUT = PROJECT_ROOT / "data" / "dataset_v4"

NO_ESPECIFICADO = "No especificado en la metodología"


def norm(t: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


# =========================================================================
# POBLACION — sujetos, unidades de analisis o corpus documental
# =========================================================================
P_POBLACION = [
    # ES / PT
    r"(?:muestra|amostra)\s+(?:de|compuesta por|constituida por|final|de conveniencia)?\s*[^.;]{8,140}",
    r"(?:participantes|sujeitos|sujetos)\s*:?\s*[^.;]{8,140}",
    r"(?:se incluyeron|fueron incluidos|se seleccionaron|foram inclu[ií]dos|foram selecionados)\s+[^.;]{8,140}",
    r"\b(?:pacientes|estudantes|estudiantes|docentes|profesionales|profissionais|adultos mayores|idosos|idosas|ni[nñ]os|ni[nñ]as|cuidadores|familias|enfermeiros|enfermeras)\b[^.;]{0,120}",
    r"\b(?:art[ií]culos|documentos|estudios|estudos|publicaciones|publica[cç][oõ]es|registros|revis[oõ]es)\b[^.;]{0,120}",
    r"\bn\s*=\s*\d[\d.,]*[^.;]{0,120}",
    # EN
    r"sample\s+(?:of|comprised|consisting|size)\s*[^.;]{8,140}",
    r"\bparticipants\b[^.;]{0,140}",
    r"(?:were included|was included|we included|were selected)\s+[^.;]{8,140}",
    r"\b(?:patients|students|teachers|professionals|older adults|children|caregivers|nurses|families)\b[^.;]{0,120}",
    r"\b(?:articles|documents|studies|publications|records|papers|reviews)\b[^.;]{0,120}",
]

# =========================================================================
# CONCEPTO — fenomeno central (pregunta de investigacion / objetivo)
# =========================================================================
C_CONCEPTO = [
    # ES / PT
    r"(?:objetivo|objetivos|finalidad)\s*:?\s*[^.;]{12,200}",
    r"(?:objetivou-se|o objetivo deste|o objetivo desta)\s*[^.;]{12,200}",
    r"(?:para\s+(?:analizar|examinar|evaluar|explorar|identificar|mapear|caracterizar|sintetizar))\s+[^.;]{12,200}",
    r"(?:para\s+(?:analisar|examinar|avaliar|explorar|identificar|mapear|caracterizar|sintetizar))\s+[^.;]{12,200}",
    r"(?:el fen[oó]meno|el concepto|la variable|la intervenci[oó]n|la exposici[oó]n|el constructo|o fen[oô]meno|o conceito)\s+[^.;]{12,180}",
    r"(?:esta revisi[oó]n|este estudio|esta scoping|esta revis[ãa]o)\s+(?:analiza|examina|explora|mapea|sintetiza|caracteriza|analisa|explora)\s+[^.;]{12,200}",
    r"(?:se analiz[oó]|se examin[oó]|se explor[oó]|se evalu[oó]|analisou-se)\s+[^.;]{12,200}",
    # EN
    r"\b(?:aim|objective|purpose)s?\s*(?:of this (?:review|study))?\s*:?\s*(?:was|were|is)?\s*[^.;]{12,200}",
    r"this\s+(?:review|study|scoping review|systematic review)\s+(?:aims?|aimed)\s+to\s+[^.;]{12,200}",
    r"\bto\s+(?:analyse|analyze|examine|explore|evaluate|identify|map|characterise|characterize|synthesise|synthesize)\s+[^.;]{12,200}",
    r"\b(?:the phenomenon|the concept|the variable|the intervention|the exposure|the construct)\b[^.;]{12,180}",
]

# =========================================================================
# CONTEXTO — geografico, temporal, sectorial o institucional
# =========================================================================
X_CONTEXTO = [
    # ES / PT
    r"(?:contexto|escenario|[aá]mbito)\s*:?\s*[^.;]{6,150}",
    r"\ben\s+(?:pa[ií]ses|regiones|hospitales|universidades|escuelas|comunidades|zonas rurales|ciudades|unidades)[^.;]{0,130}",
    r"\b(?:no Brasil|no Brasil e|em Portugal|na Iberoam[eé]rica|na Am[eé]rica Latina|em pa[ií]ses)[^.;]{0,130}",
    r"\b(?:Am[eé]rica Latina|Iberoam[eé]rica|Brasil|Espa[nñ]a|Portugal|M[eé]xico|Colombia|Chile|Argentina|Per[uú]|Ecuador|Cuba|Uruguay|Bolivia)\b[^.;]{0,130}",
    r"(?:entre|desde|de)\s+(?:19|20)\d{2}\s*(?:y|a|-|hasta|e)\s*(?:19|20)\d{2}",
    r"\b(?:publicados?|publicadas?|publicados entre)\s+entre\s+(?:19|20)\d{2}[^.;]{0,40}",
    r"\b(?:atenci[oó]n primaria|atenci[oó]n secundaria|atenci[oó]n terciaria|aten[çc][aã]o prim[áa]ria)\b[^.;]{0,110}",
    # EN
    r"\bcontext\s*:?\s*[^.;]{6,150}",
    r"\bin\s+(?:countries|regions|hospitals|universities|schools|communities|rural areas|cities)[^.;]{0,130}",
    r"\b(?:Latin America|Ibero-?America|Brazil|Spain|Portugal|Mexico|Colombia|Chile|Argentina|Peru|Ecuador|United States|USA|Canada|United Kingdom|UK)\b[^.;]{0,130}",
    r"\bbetween\s+(?:19|20)\d{2}\s+and\s+(?:19|20)\d{2}[^.;]{0,60}",
    r"\b(?:primary care|secondary care|tertiary care|hospital setting|community setting)\b[^.;]{0,110}",
]

# =========================================================================
# DISENO — tipo de estudio o revision
# =========================================================================
D_DISENO = [
    r"\b(?:revisi[oó]n sistem[aá]tica(?:\s+de\s+la\s+literatura)?|revis[ãa]o sistem[áa]tica|systematic review)\b[^.;]{0,130}",
    r"\b(?:revisi[oó]n de alcance|scoping review|revis[ãa]o de escopo|revisi[oó]n integrativa|revis[ãa]o integrativa|integrative review|meta-?an[aá]lisis|meta-?analysis|metan[áa]lise|revisi[oó]n narrativa|narrative review|umbrella review)\b[^.;]{0,130}",
    r"\b(?:estudo\s+(?:transversal|cualitativo|quantitativo|misto)|estudio\s+(?:transversal|cualitativo|cuantitativo|mixto)|cross-sectional study|cohort study|qualitative study|quantitative study|mixed methods)\b[^.;]{0,130}",
    r"\b(?:dise[nñ]o|design|delineamento)\s*:?\s*[^.;]{6,150}",
]

CAMPOS: dict[str, dict] = {
    "poblacion": {"fuentes": ["methods"], "patrones": P_POBLACION},
    "concepto": {"fuentes": ["abstract", "methods"], "patrones": C_CONCEPTO},
    "contexto": {"fuentes": ["methods", "abstract"], "patrones": X_CONTEXTO},
    "diseno": {"fuentes": ["methods", "abstract"], "patrones": D_DISENO},
}

NEGACIONES = {
    "poblacion": ["no se especifica la poblacion", "no especifica la poblacion", "nao especifica a populacao",
                  "no participants", "population was not specified"],
    "concepto": ["no se especifica el concepto", "no especifica el concepto", "nao especifica o conceito"],
    "contexto": ["no se especifica el contexto", "no especifica el contexto", "nao especifica o contexto",
                 "sin delimitacion geografica", "no delimita el contexto", "not specified"],
    "diseno": ["no se especifica el diseno", "no especifica el diseno"],
}

RELLENO = {
    "articulos cientificos", "documentos indexados", "la literatura", "estudios", "articles",
    "iberoamerica", "el contexto", "diversos contextos", "no aplica", "general", "revision",
}


def _ventana(texto: str, start: int, end: int, antes: int = 30, despues: int = 70) -> str:
    """Span VERBATIM alrededor del match, recortado en fronteras de oracion."""
    a = max(0, start - antes)
    b = min(len(texto), end + despues)
    frag = texto[a:b]
    rel_s, rel_e = start - a, end - a
    for sep in (". ", "; ", "\n", "? "):
        i = frag.rfind(sep, 0, rel_s)
        if i != -1:
            frag = frag[i + len(sep):]
            rel_s -= i + len(sep)
            rel_e -= i + len(sep)
            break
    for sep in (". ", "; ", "\n", "? "):
        j = frag.find(sep, rel_e)
        if j != -1:
            frag = frag[:j]
            break
    return re.sub(r"\s+", " ", frag).strip(" .,;:")


def extraer(metodo: str, patrones: list[str]) -> str | None:
    for pat in patrones:
        for m in re.finditer(pat, metodo, re.IGNORECASE):
            span = _ventana(metodo, m.start(), m.end())
            if len(norm(span)) < 8 or norm(span) in RELLENO:
                continue
            if span not in metodo:  # guardián de grounding
                continue
            return span
    return None


def etiquetar(sections: dict) -> dict:
    fuentes_txt = {
        "methods": sections.get("methods") or "",
        "abstract": (sections.get("abstract") or "") + "\n" + (sections.get("abstract_alt") or ""),
    }
    salida: dict = {}
    avisos: list[str] = []
    for campo, cfg in CAMPOS.items():
        valor, fuente = None, "AUSENTE"
        for f in cfg["fuentes"]:
            txt = fuentes_txt.get(f) or ""
            if not txt:
                continue
            v = extraer(txt, cfg["patrones"])
            if v:
                valor, fuente = v, f.upper()
                break
        if valor is None:
            # negacion explicita en cualquier fuente
            for f, txt in fuentes_txt.items():
                n = norm(txt)
                if any(x in n for x in NEGACIONES[campo]):
                    avisos.append(f"{campo}: ausencia declarada explícitamente ({f})")
                    break
            valor = NO_ESPECIFICADO
            fuente = "NO_ESPECIFICADO"
        salida[campo] = valor
        salida[f"{campo}_fuente"] = fuente
    salida["avisos"] = avisos
    return salida


def main() -> None:
    inv = json.loads((CORPUS_V2 / "inventario_unicos.json").read_text(encoding="utf-8"))
    filas = []
    for rec in inv["unicos"]:
        if not rec["usabilidad"]["T2"]:
            continue
        sect = rec.get("sections") or {}
        lab = etiquetar(sect)
        filas.append({
            "lote": rec.get("lote"),
            "doi_filename": rec["doi_filename"],
            "area": rec["area"],
            "idioma": rec["idioma"],
            "metodo_chars": len(sect.get("methods") or ""),
            **lab,
        })

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "t2_pcc.jsonl", "w", encoding="utf-8") as fh:
        for r in filas:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    campos = ("poblacion", "concepto", "contexto", "diseno")
    n = len(filas)
    diag = {
        "n_articulos": n,
        "cobertura": {c: sum(1 for r in filas if r[c] != NO_ESPECIFICADO) for c in campos},
        "cobertura_pct": {c: round(sum(1 for r in filas if r[c] != NO_ESPECIFICADO) / n * 100, 1) if n else 0.0
                          for c in campos},
        "fuente": {c: dict(Counter(r[f"{c}_fuente"] for r in filas).most_common()) for c in campos},
        "cobertura_por_idioma": {
            i: {c: sum(1 for r in filas if r["idioma"] == i and r[c] != NO_ESPECIFICADO) for c in campos}
            for i in sorted({r["idioma"] for r in filas})
        },
        "articulos_con_pcc_completo": sum(
            1 for r in filas if all(r[c] != NO_ESPECIFICADO for c in ("poblacion", "concepto", "contexto"))
        ),
        "avisos": dict(Counter(a for r in filas for a in r["avisos"]).most_common()),
    }
    (OUT / "diagnostico_t2.json").write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print("MATRIZ JBI PCC (T2) — EXTRACCION VERBATIM CON GUARDIAN DE GROUNDING")
    print("=" * 78)
    print(f"Articulos T2 utilizables: {n}")
    print("\nCobertura por campo (span verbatim hallado en la fuente declarada):")
    for c in campos:
        print(f"    {c:12} {diag['cobertura'][c]:4}/{n}  ({diag['cobertura_pct'][c]:5.1f} %)")
    print("\nFuente del dato:")
    for c in campos:
        print(f"    {c:12} {diag['fuente'][c]}")
    print(f"\nCobertura por idioma: {diag['cobertura_por_idioma']}")
    print(f"Articulos con PCC (P+C+C) completo: {diag['articulos_con_pcc_completo']}/{n}")
    print(f"Avisos: {diag['avisos']}")
    print(f"\nSalida: {OUT / 't2_pcc.jsonl'}")
    print("=" * 78)


if __name__ == "__main__":
    main()
