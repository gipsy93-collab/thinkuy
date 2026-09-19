"""Etiquetador determinista del TIPO DE PROTOCOLO DE SÍNTESIS (T1 reformulado).

Reemplaza la taxonomia de 5 roles epistemicos (no operacionalizable en un corpus
compuesto solo de revisiones: 62,4 % de una clase, dos clases vacias) por TRES EJES
ORTOGONALES, cada uno verificable contra un estandar normativo publicado:

    R1 - guia de reporte declarada : PRISMA_2020 | PRISMA_ScR | ENTREQ | MOOSE | NONE_DECLARED
    R2 - marco de conduccion       : JBI | COCHRANE | ARKSEY_OMALLEY | EPPI | NONE_DECLARED
    R3 - tipo de sintesis          : META_ANALYSIS | META_SYNTHESIS | THEMATIC_SYNTHESIS |
                                     DESCRIPTIVE_MAPPING | NARRATIVE | NONE

Reglas duras:
  * Lista cerrada de marcadores ES + PT + EN.
  * Deteccion de NEGACION: "no fue posible realizar un meta-analisis" NO es meta-analisis.
  * Si no hay declaracion explicita => NONE_DECLARED (jamas se adivina).
  * La taxonomia de 5 roles NO se elimina: queda como metadato descriptivo del articulo.

NO usa modelos de lenguaje.

USO:
    python tools/etiquetador_protocolo.py
SALIDA:
    data/dataset_v4/protocolo_revision.jsonl
    data/dataset_v4/diagnostico_protocolo.json
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORPUS_V2 = PROJECT_ROOT / "data" / "corpus_v2"
OUT = PROJECT_ROOT / "data" / "dataset_v4"


def norm(t: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


# =========================================================================
# R1 - GUIA DE REPORTE DECLARADA
# =========================================================================
R1 = [
    ("PRISMA_ScR", ["prisma-scr", "prisma scr", "prisma extension for scoping", "prisma-scr guidelines"]),
    ("PRISMA_2020", ["prisma 2020", "prisma-2020", "preferred reporting items for systematic reviews and meta-analyses 2020",
                     "prisma 2020 statement", "declaracion prisma 2020"]),
    ("PRISMA_2020", ["prisma", "preferred reporting items for systematic reviews"]),
    ("ENTREQ", ["entreng", "entreng statement", "entreq"]),
    ("MOOSE", ["moose", "meta-analysis of observational studies in epidemiology"]),
    ("STROBE", ["strobe"]),
]

# =========================================================================
# R2 - MARCO METODOLOGICO DE CONDUCCION
# =========================================================================
R2 = [
    ("JBI", ["jbi", "joanna briggs", "instituto joanna briggs", "jbi evidence synthesis", "jbi manual"]),
    ("COCHRANE", ["cochrane", "manual cochrane", "cochrane handbook", "cochrane collaboration"]),
    ("ARKSEY_OMALLEY", ["arksey", "o'malley", "omalley", "arksey and o'malley", "arksey y o'malley"]),
    ("EPPI", ["eppi", "eppi-centre", "evidence for policy and practice"]),
]

# =========================================================================
# R3 - TIPO DE SINTESIS
# =========================================================================
R3 = [
    ("META_ANALYSIS", ["meta-analisis", "metaanalisis", "meta-analisis", "meta analysis", "meta-analysis",
                       "meta-analitico", "meta-analitica", "metanalise", "metanalise"]),
    ("META_SYNTHESIS", ["meta-sintesis", "metasintesis", "meta-synthesis", "metasynthesis", "meta-sintese"]),
    ("THEMATIC_SYNTHESIS", ["sintesis tematica", "analisis tematico", "thematic synthesis", "thematic analysis",
                            "sintese tematica", "analise tematica"]),
    ("DESCRIPTIVE_MAPPING", ["mapeo", "mapping", "mapa de evidencia", "evidence map", "mapeamento",
                             "caracterizacion descriptiva"]),
    ("NARRATIVE", ["sintesis narrativa", "narrative synthesis", "sintese narrativa", "revision narrativa"]),
]

# Negacion que invalida el marcador de sintesis
NEGACIONES = [
    "no fue posible", "no se pudo", "no fue viable", "no permitio", "no posibilito",
    "not possible", "could not be performed", "was not possible", "unable to",
    "nao foi possivel", "nao foi viavel", "inviable",
]

# Contextos de DECLARACIÓN (corrección tras el Gate 2): la mera aparición del término no
# equivale a declararlo. Se cita el manual Cochrane sin seguirlo, o se menciona un
# metaanálisis ajeno sin realizarlo. El marcador solo se acredita si va precedido por una
# construcción que indique que el artículo DECLARA su conducción.
DECLARACION_CUES = [
    # ES
    "se siguio", "seguimos", "siguiendo", "guiada por", "guiado por", "se guio",
    "de acuerdo con el", "de acuerdo con la", "segun el", "segun la", "conforme a",
    "basada en", "basado en", "se adopto", "se utilizo", "se empleo", "se aplico",
    "cumpliendo", "atendiendo a", "bajo las directrices", "declaracion", "declaramos",
    "se realizo", "se llevo a cabo", "se efectuo", "se desarrollo", "los datos se",
    "sintetizados mediante", "analizados mediante", "por medio de", "utilizando el manual",
    # PT
    "seguimos", "seguindo", "guiada por", "guiado por", "de acordo com o", "de acordo com a",
    "segundo o", "segundo a", "baseada em", "baseado em", "adotou-se", "utilizou-se",
    "realizou-se", "foi realizado", "os dados foram", "por meio de",
    # EN
    "we followed", "following the", "guided by", "in accordance with", "according to the",
    "based on the", "was conducted in accordance", "reported in accordance", "adhered to",
    "we used", "we adopted", "we conducted", "we performed", "we carried out",
    "was performed", "was conducted", "data were", "synthesised using", "synthesized using",
    "using the manual", "complied with",
]


def en_contexto_de_declaracion(texto_n: str, pos: int, radio: int = 160) -> bool:
    """¿El marcador en `pos` va precedido por una construcción de declaración?"""
    ventana = texto_n[max(0, pos - radio):pos]
    return any(norm(c) in ventana for c in DECLARACION_CUES)


def detectar(texto: str, compilado, exigir_declaracion: bool = False):
    """Devuelve (valor_prioritario, todos_los_valores, hubo_negacion_anuladora)."""
    t = norm(texto)
    encontrados: list[str] = []
    negacion = False
    for valor, pats in compilado:
        for p in pats:
            m = p.search(t)
            if m:
                if _negado(t, m.start()):
                    negacion = True
                    continue
                if exigir_declaracion and not en_contexto_de_declaracion(t, m.start()):
                    continue  # mención, no declaración
                encontrados.append(valor)
                break
    if not encontrados:
        return "NONE_DECLARED", [], negacion
    return encontrados[0], encontrados, negacion


def _compilar(lista: list[tuple[str, list[str]]]) -> list[tuple[str, list[re.Pattern]]]:
    out = []
    for valor, frases in lista:
        pats = [re.compile(r"(?<![a-z0-9])" + re.escape(norm(f)) + r"(?![a-z0-9])") for f in frases if norm(f)]
        if pats:
            out.append((valor, pats))
    return out


R1_C, R2_C, R3_C = _compilar(R1), _compilar(R2), _compilar(R3)


def _negado(texto_n: str, pos: int, radio: int = 120) -> bool:
    """¿El marcador en `pos` está bajo una negación cercana?"""
    ventana = texto_n[max(0, pos - radio):pos]
    return any(n in ventana for n in NEGACIONES)


def etiquetar(rec: dict) -> dict:
    sect = rec.get("sections") or {}
    abstract = (sect.get("abstract") or "") + "\n" + (sect.get("abstract_alt") or "")
    methods = sect.get("methods") or ""
    cuerpo = "\n\n".join(v for k, v in sect.items() if k != "references" and v)

    # Nivel 1 (alta precision): metodos + abstract. Nivel 2 (cobertura): cuerpo completo.
    texto_n1 = f"{abstract}\n{methods}"

    salida: dict = {}
    avisos: list[str] = []
    for eje, compilado, clave in (("R1", R1_C, "R1_guia_reporte"),
                                  ("R2", R2_C, "R2_marco_conduccion"),
                                  ("R3", R3_C, "R3_tipo_sintesis")):
        # R1 se declara con el acrónimo y suele coincidir; R2 y R3 exigen contexto de
        # declaración porque el término también aparece en citas y menciones (Gate 2).
        exigir = eje in ("R2", "R3")
        valor, todos, neg = detectar(texto_n1, compilado, exigir_declaracion=exigir)
        origen = "METODOS"
        if valor == "NONE_DECLARED":
            valor2, todos2, neg2 = detectar(cuerpo, compilado, exigir_declaracion=exigir)
            if valor2 != "NONE_DECLARED":
                valor, todos, neg, origen = valor2, todos2, neg2, "CUERPO"
        salida[clave] = valor
        salida[clave.replace("_guia_reporte", "_declaradas").replace("_marco_conduccion", "_declaradas")
               .replace("_tipo_sintesis", "_declaradas")] = todos
        salida[clave + "_origen"] = origen if valor != "NONE_DECLARED" else "AUSENTE"
        if neg:
            avisos.append(f"{clave}: marcador de sintesis bajo negacion (no acreditado)")

    if salida["R1_guia_reporte"] == "PRISMA_ScR" and "PRISMA_2020" in (salida.get("R1_declaradas") or []):
        avisos.append("declara PRISMA y PRISMA-ScR; se conserva la variante especifica (ScR)")
    if salida["R2_marco_conduccion"] == "NONE_DECLARED" and salida["R3_tipo_sintesis"] == "NONE_DECLARED":
        avisos.append("sin marco ni tipo de sintesis declarados en ninguna seccion")

    salida["avisos"] = avisos
    return salida


def construir_control_protocolo(filas: list[dict], inv: dict, por_idioma: int = 4, semilla: int = 3407) -> list[dict]:
    """Muestra de control para los ejes R1/R2/R3: 4 por idioma, con la evidencia a la vista."""
    import random
    rnd = random.Random(semilla)
    por_ruta = {r["ruta_relativa"]: r for r in inv["unicos"]}
    muestra: list[dict] = []
    for idioma in ("ES", "PT", "EN"):
        pool = [f for f in filas if f["idioma"] == idioma]
        declarados = [f for f in pool if f["R1_guia_reporte"] != "NONE_DECLARED" or f["R3_tipo_sintesis"] != "NONE_DECLARED"]
        ausentes = [f for f in pool if f not in declarados]
        sel = rnd.sample(declarados, min(3, len(declarados))) + rnd.sample(ausentes, min(1, len(ausentes)))
        for i, f in enumerate(sel, 1):
            rec = por_ruta.get(f.get("ruta_relativa", ""), {})
            sect = rec.get("sections") or {}
            evidencia = (sect.get("methods") or "")[:400]
            copia = dict(f)
            copia["control_id"] = f"P-{idioma}-{i:02d}"
            copia["evidencia"] = evidencia
            muestra.append(copia)
    return muestra


def main() -> None:
    inv = json.loads((CORPUS_V2 / "inventario_unicos.json").read_text(encoding="utf-8"))
    filas = []
    for rec in inv["unicos"]:
        if not rec["usabilidad"]["T1"]:
            continue
        lab = etiquetar(rec)
        filas.append({
            "lote": rec.get("lote"),
            "doi_filename": rec["doi_filename"],
            "ruta_relativa": rec.get("ruta_relativa"),
            "area": rec["area"],
            "idioma": rec["idioma"],
            **lab,
        })

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "protocolo_revision.jsonl", "w", encoding="utf-8") as fh:
        for r in filas:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    diag = {
        "n_articulos": len(filas),
        "R1": dict(Counter(r["R1_guia_reporte"] for r in filas).most_common()),
        "R2": dict(Counter(r["R2_marco_conduccion"] for r in filas).most_common()),
        "R3": dict(Counter(r["R3_tipo_sintesis"] for r in filas).most_common()),
        "origen_declaracion": {
            "R1": dict(Counter(r["R1_guia_reporte_origen"] for r in filas).most_common()),
            "R2": dict(Counter(r["R2_marco_conduccion_origen"] for r in filas).most_common()),
            "R3": dict(Counter(r["R3_tipo_sintesis_origen"] for r in filas).most_common()),
        },
        "R1_por_idioma": {i: dict(Counter(r["R1_guia_reporte"] for r in filas if r["idioma"] == i).most_common())
                          for i in sorted({r["idioma"] for r in filas})},
        "R3_por_idioma": {i: dict(Counter(r["R3_tipo_sintesis"] for r in filas if r["idioma"] == i).most_common())
                          for i in sorted({r["idioma"] for r in filas})},
        "con_sin_declarar": sum(1 for r in filas if r["R1_guia_reporte"] == "NONE_DECLARED"),
        "avisos": dict(Counter(a for r in filas for a in r["avisos"]).most_common()),
    }
    (OUT / "diagnostico_protocolo.json").write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print("TIPO DE PROTOCOLO DE SINTESIS — T1 REFORMULADO")
    print("=" * 78)
    print(f"Articulos: {diag['n_articulos']}")
    for eje, etiqueta in (("R1", "Guia de reporte (PRISMA 2020 / PRISMA-ScR / ENTREQ / MOOSE)"),
                          ("R2", "Marco de conduccion (JBI / Cochrane / Arksey / EPPI)"),
                          ("R3", "Tipo de sintesis")):
        print(f"\n{eje} — {etiqueta}")
        for k, v in diag[eje].items():
            print(f"    {v:4}  {k}")
    print("\nOrigen de la declaracion (METODOS = alta precision, CUERPO = cobertura):")
    for eje, d in diag["origen_declaracion"].items():
        print(f"    {eje}: {d}")
    print(f"\nSin guia declarada: {diag['con_sin_declarar']}")
    print(f"Avisos: {diag['avisos']}")

    control = construir_control_protocolo(filas, inv)
    with open(OUT / "control_protocolo_12.tsv", "w", encoding="utf-8") as fh:
        fh.write("control_id\tidioma\tarchivo\tR1\tR1_origen\tR2\tR2_origen\tR3\tR3_origen\tR1_humano\tR2_humano\tR3_humano\tnota\n")
        for r in control:
            fh.write("\t".join([
                r["control_id"], r["idioma"], r["doi_filename"],
                r["R1_guia_reporte"], r["R1_guia_reporte_origen"],
                r["R2_marco_conduccion"], r["R2_marco_conduccion_origen"],
                r["R3_tipo_sintesis"], r["R3_tipo_sintesis_origen"],
                "", "", "", "",
            ]) + "\n")
    with open(OUT / "control_protocolo_12.md", "w", encoding="utf-8") as fh:
        fh.write("# Control humano — TIPO DE PROTOCOLO (T1 reformulado)\n\n")
        fh.write("Verifica R1, R2 y R3 contra el texto. Si no consta, escribe `NONE_DECLARED`.\n\n")
        fh.write("- R1: `PRISMA_2020` | `PRISMA_ScR` | `ENTREQ` | `MOOSE` | `NONE_DECLARED`\n")
        fh.write("- R2: `JBI` | `COCHRANE` | `ARKSEY_OMALLEY` | `EPPI` | `NONE_DECLARED`\n")
        fh.write("- R3: `META_ANALYSIS` | `META_SYNTHESIS` | `THEMATIC_SYNTHESIS` | `DESCRIPTIVE_MAPPING` | `NARRATIVE` | `NONE`\n\n")
        for r in control:
            fh.write(f"## {r['control_id']} — {r['idioma']} — `{r['doi_filename']}`\n\n")
            fh.write(f"**Regla propone:** R1=`{r['R1_guia_reporte']}` ({r['R1_guia_reporte_origen']}) · "
                     f"R2=`{r['R2_marco_conduccion']}` ({r['R2_marco_conduccion_origen']}) · "
                     f"R3=`{r['R3_tipo_sintesis']}` ({r['R3_tipo_sintesis_origen']})\n\n")
            fh.write(f"**Inicio de la metodología:**\n\n> {(r.get('evidencia') or '')[:400]}\n\n")
            fh.write("**Tu verificación:** R1=`____` · R2=`____` · R3=`____` · nota: ____\n\n---\n\n")
    print(f"Control de protocolo: {len(control)} casos -> {OUT / 'control_protocolo_12.md'}")

    print(f"\nSalida: {OUT / 'protocolo_revision.jsonl'}")
    print("=" * 78)


if __name__ == "__main__":
    main()
