"""Genera los pases de anotación dimensión por dimensión y la hoja de protocolo con casillas.

Por qué: codificar los tres ejes a la vez en una sola fila induce a marcar solo uno
(comportamiento observado en el IP en dos rondas). Codificar UNA dimensión por pasada, sobre
los mismos 36 casos, es el método estándar en análisis de contenido y reduce el sesgo de halo.

Salidas:
    pase1_postura.csv          — 36 filas, una columna: A_postura
    pase2_certeza.csv          — 36 filas, una columna: B_certeza
    pase3_funcion.csv          — 36 filas, una columna: C_funcion
    control_protocolo_12_ANOTAR.md — 12 casos con casillas para marcar

Las marcas que el IP ya hizo se conservan precargadas.

USO:
    python tools/generar_pases_anotacion.py
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
D = PROJECT_ROOT / "data" / "dataset_v4"

# Casos cuya oración el IP marcó como insuficiente (se excluyen del cálculo y se anotan aparte)
INSUFICIENTES_DECLARADOS = {"PT-11", "PT-12", "PT-13", "PT-14", "PT-15"}

VALORES = {
    "A_postura": ["SUPPORT", "CONFLICT", "NEUTRAL", "AMBIGUO"],
    "B_certeza": ["STRONG", "MODERATE", "WEAK", "NO_DECLARADA", "AMBIGUO"],
    "C_funcion": ["REPORT", "METHOD_ADOPTION", "GAP", "CONCESSION_REDEFINITION", "OWN_CLAIM", "AMBIGUO"],
}


def leer(path: Path, delim: str = ",") -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delim))


def escribir_pase(nombre: str, control: list[dict], hoja: list[dict], col: str) -> int:
    marca_prev = {(r.get("control_id") or "").strip(): (r.get(col) or "").strip().upper() for r in hoja}
    p = D / nombre
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["control_id", "idioma", "oracion_resumida", col, "observacion"])
        for c in control:
            cid = c["control_id"].strip()
            oracion = " ".join((c["oracion"] or "").split())
            w.writerow([
                cid,
                c["idioma"],
                (oracion[:180] + "…") if len(oracion) > 180 else oracion,
                marca_prev.get(cid, ""),
                "ORACION_INSUFICIENTE" if cid in INSUFICIENTES_DECLARADOS else "",
            ])
    return len(control)


def escribir_protocolo() -> int:
    """Casillas para marcar, con el texto a la vista. Mucho más simple que teclear códigos."""
    tsv = (D / "control_protocolo_12.tsv").read_text(encoding="utf-8-sig").splitlines()
    filas = [l.split("\t") for l in tsv[1:] if l.strip()]
    inv = json.loads((PROJECT_ROOT / "data" / "corpus_v2" / "inventario_unicos.json").read_text(encoding="utf-8"))
    por_nombre = {r["doi_filename"]: r for r in inv["unicos"]}

    lineas = [
        "# Protocolo de las revisiones — anotación con casillas",
        "",
        "Para cada artículo, marca **una casilla por eje** (tres en total).",
        "Sustituye `[ ]` por `[x]`. Si el dato no aparece, marca `NONE_DECLARED` / `NONE`.",
        "",
        "Qué significa cada columna:",
        "",
        "| Eje | Pregunta |",
        "|---|---|",
        "| **R1** guía de reporte | ¿El artículo dice explícitamente que siguió **PRISMA 2020**, **PRISMA-ScR**, **ENTREQ**, **MOOSE** o **STROBE**? ¿O no declara ninguna? |",
        "| **R2** marco de conducción | ¿Declara haberse guiado por el **manual JBI**, la **Colaboración Cochrane**, el marco de **Arksey y O'Malley** o **EPPI**? |",
        "| **R3** tipo de síntesis | ¿Hace **meta-análisis**, **meta-síntesis**, **síntesis temática**, **mapeo descriptivo** o **síntesis narrativa**? |",
        "",
        "Nota: R1 y R2 pueden coexistir (un artículo puede seguir PRISMA y conducirse según JBI). R3 es independiente.",
        "",
        "---",
        "",
    ]
    for c in filas:
        cid, idioma, archivo = c[0], c[1], c[2]
        rec = por_nombre.get(archivo, {})
        sect = rec.get("sections") or {}
        abstract = " ".join(((sect.get("abstract") or sect.get("abstract_alt") or ""))[:600].split())
        methods = " ".join((sect.get("methods") or "")[:800].split())
        lineas += [
            f"## {cid} — {idioma} — `{archivo}`",
            "",
            f"**Abstract:** {abstract}",
            "",
            f"**Inicio de la metodología:** {methods}",
            "",
            "**R1 — guía de reporte declarada** (una):",
            "```",
            "[ ] PRISMA_2020      [ ] PRISMA_ScR      [ ] ENTREQ      [ ] MOOSE      [ ] STROBE      [ ] NONE_DECLARED",
            "```",
            "**R2 — marco de conducción** (una):",
            "```",
            "[ ] JBI      [ ] COCHRANE      [ ] ARKSEY_OMALLEY      [ ] EPPI      [ ] NONE_DECLARED",
            "```",
            "**R3 — tipo de síntesis** (una):",
            "```",
            "[ ] META_ANALYSIS   [ ] META_SYNTHESIS   [ ] THEMATIC_SYNTHESIS   [ ] DESCRIPTIVE_MAPPING   [ ] NARRATIVE   [ ] NONE",
            "```",
            "nota: ",
            "",
            "---",
            "",
        ]
    (D / "control_protocolo_12_ANOTAR.md").write_text("\n".join(lineas), encoding="utf-8")
    return len(filas)


def main() -> None:
    control = leer(D / "control_36.tsv", delim="\t")
    hoja = leer(D / "hoja_respuestas_stance.csv", delim=",")

    n1 = escribir_pase("pase1_postura.csv", control, hoja, "A_postura")
    n2 = escribir_pase("pase2_certeza.csv", control, hoja, "B_certeza")
    n3 = escribir_pase("pase3_funcion.csv", control, hoja, "C_funcion")
    n4 = escribir_protocolo()

    ya = {
        "A_postura": sum(1 for r in hoja if (r.get("A_postura") or "").strip()),
        "B_certeza": sum(1 for r in hoja if (r.get("B_certeza") or "").strip()),
        "C_funcion": sum(1 for r in hoja if (r.get("C_funcion") or "").strip()),
    }
    print("PASES GENERADOS (una dimensión por archivo, 36 casos cada uno)")
    print(f"  pase1_postura.csv  -> {n1} filas  (ya tienes {ya['A_postura']} marcas precargadas)")
    print(f"  pase2_certeza.csv  -> {n2} filas  (ya tienes {ya['B_certeza']} marcas precargadas)")
    print(f"  pase3_funcion.csv  -> {n3} filas  (ya tienes {ya['C_funcion']} marcas precargadas)")
    print(f"  protocolo con casillas -> {n4} casos  (control_protocolo_12_ANOTAR.md)")
    print()
    print(f"Casos marcados como oración insuficiente (excluidos del cálculo): {sorted(INSUFICIENTES_DECLARADOS)}")
    print("Valores admitidos:")
    for k, v in VALORES.items():
        print(f"  {k}: {' | '.join(v)}")


if __name__ == "__main__":
    main()
