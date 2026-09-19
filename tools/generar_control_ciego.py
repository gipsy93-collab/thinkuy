"""Genera las versiones CIEGAS de las muestras de control (Gate 2).

Anotar viendo lo que propone la regla introduce sesgo de anclaje e invalida el kappa.
Este script produce copias sin la propuesta del etiquetador, preservando el mismo orden
y los mismos identificadores, de modo que luego puedan compararse celda a celda.

USO:
    python tools/generar_control_ciego.py
SALIDAS:
    data/dataset_v4/control_36_CIEGO.md
    data/dataset_v4/control_protocolo_12_CIEGO.md
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
D = PROJECT_ROOT / "data" / "dataset_v4"


def control_stance_ciego() -> int:
    filas = [l for l in (D / "control_36.tsv").read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
    lineas = [
        "# Control ciego — STANCE (36 casos)",
        "",
        "**Cada caso recibe TRES marcas: una por eje.** A, B y C son preguntas independientes,",
        "no una categoría con opciones dentro.",
        "",
        "Anota **A**, **B** y **C** para cada caso. Valores permitidos (ver `CODEBOOK_GATE2.md`):",
        "",
        "- **A** (postura): `SUPPORT` | `CONFLICT` | `NEUTRAL`",
        "- **B** (certeza): `STRONG` | `MODERATE` | `WEAK` | `NO_DECLARADA`",
        "- **C** (función): `REPORT` | `METHOD_ADOPTION` | `GAP` | `CONCESSION_REDEFINITION` | `OWN_CLAIM`",
        "",
        "Si dos valores del MISMO eje coexisten, aplica la tabla de prioridad del codebook (§1bis)",
        "y registra el segundo en `nota` como `+VALOR`.",
        "",
        "Si no puedes decidir: `AMBIGUO`. No dejes celdas vacías.",
        "",
        "---",
        "",
    ]
    for i, linea in enumerate(filas, 1):
        c = linea.split("\t")
        cid, idioma, oracion, parrafo = c[0], c[1], c[2], c[3]
        lineas += [
            f"## {cid} — {idioma}",
            "",
            f"**Oración:** {oracion}",
            "",
            f"**Contexto:** {parrafo[:700]}",
            "",
            "**Tu etiqueta — completa las TRES líneas:**",
            "",
            "```",
            "A_postura  (SUPPORT | CONFLICT | NEUTRAL)          = ",
            "B_certeza  (STRONG | MODERATE | WEAK | NO_DECLARADA) = ",
            "C_funcion  (REPORT | METHOD_ADOPTION | GAP | CONCESSION_REDEFINITION | OWN_CLAIM) = ",
            "nota (opcional; si hay un segundo valor en el mismo eje, escríbelo como +VALOR) = ",
            "```",
            "",
            "---",
            "",
        ]
    (D / "control_36_CIEGO.md").write_text("\n".join(lineas), encoding="utf-8")
    return len(filas)


def control_protocolo_ciego() -> int:
    """El control de protocolo NO puede ser ciego en la evidencia (hay que ver la declaración),
    pero sí oculta la propuesta de la regla: se muestra el texto y se pide la decisión."""
    filas = [l for l in (D / "control_protocolo_12.tsv").read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
    inv = json.loads((PROJECT_ROOT / "data" / "corpus_v2" / "inventario_unicos.json").read_text(encoding="utf-8"))
    por_nombre = {r["doi_filename"]: r for r in inv["unicos"]}

    lineas = [
        "# Control de protocolo (12 casos) — propuesta de la regla OCULTA",
        "",
        "Verifica R1, R2 y R3 leyendo el inicio de la metodología.",
        "",
        "- **R1** (guía de reporte): `PRISMA_2020` | `PRISMA_ScR` | `ENTREQ` | `MOOSE` | `STROBE` | `NONE_DECLARED`",
        "- **R2** (marco de conducción): `JBI` | `COCHRANE` | `ARKSEY_OMALLEY` | `EPPI` | `NONE_DECLARED`",
        "- **R3** (tipo de síntesis): `META_ANALYSIS` | `META_SYNTHESIS` | `THEMATIC_SYNTHESIS` | `DESCRIPTIVE_MAPPING` | `NARRATIVE` | `NONE`",
        "",
        "---",
        "",
    ]
    for linea in filas:
        c = linea.split("\t")
        cid, idioma, archivo = c[0], c[1], c[2]
        rec = por_nombre.get(archivo, {})
        sect = rec.get("sections") or {}
        abstract = (sect.get("abstract") or sect.get("abstract_alt") or "")[:700]
        methods = (sect.get("methods") or "")[:900]
        lineas += [
            f"## {cid} — {idioma} — `{archivo}`",
            "",
            "**Abstract:**",
            "",
            f"> {abstract}",
            "",
            "**Inicio de la metodología:**",
            "",
            f"> {methods}",
            "",
            "**Tu verificación:** R1=`____` · R2=`____` · R3=`____` · nota: ____",
            "",
            "---",
            "",
        ]
    (D / "control_protocolo_12_CIEGO.md").write_text("\n".join(lineas), encoding="utf-8")
    return len(filas)


def main() -> None:
    n1 = control_stance_ciego()
    n2 = control_protocolo_ciego()
    print(f"Control ciego de stance    : {n1} casos -> {D / 'control_36_CIEGO.md'}")
    print(f"Control de protocolo       : {n2} casos -> {D / 'control_protocolo_12_CIEGO.md'}")


if __name__ == "__main__":
    main()
