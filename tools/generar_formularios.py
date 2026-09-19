"""Genera formularios con CASILLAS y preguntas en lenguaje llano (una pregunta por archivo).

Motivo: dos rondas de anotación mostraron que (a) una fila con tres celdas induce a marcar
una sola, (b) los códigos canónicos obligan a memorizar una taxonomía, (c) precargar los
archivos hace que parezcan terminados. Este generador produce:

    RESPONDER_1_ACUERDO.md    — solo los casos PENDIENTES de postura
    RESPONDER_2_FUERZA.md     — solo los casos PENDIENTES de certeza
    RESPONDER_3_FUNCION.md    — solo los casos PENDIENTES de función retórica
    RESPONDER_4_PROTOCOLO.md  — 12 casos, búsqueda literal de palabras clave

Cada caso se responde marcando UNA casilla. No hay que escribir códigos.

USO:
    python tools/generar_formularios.py
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
D = PROJECT_ROOT / "data" / "dataset_v4"

INSUFICIENTES = {"PT-11", "PT-12", "PT-13", "PT-14", "PT-15"}


def leer(path: Path, delim: str = ",") -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delim))


def bloque(cid: str, idioma: str, oracion: str, pregunta: str, opciones: list[tuple[str, str]]) -> str:
    o = " ".join(oracion.split())
    if len(o) > 400:
        o = o[:400] + "…"
    l = [f"### {cid} ({idioma})", "", f"> {o}", "", f"**{pregunta}**", ""]
    for marca, texto in opciones:
        l.append(f"- [ ] **{marca}** — {texto}")
    l += ["", "---", ""]
    return "\n".join(l)


def generar_pregunta(nombre: str, titulo: str, explicacion: str, col: str,
                     opciones: list[tuple[str, str]]) -> int:
    control = leer(D / "control_36.tsv", delim="\t")
    respuestas = {(r.get("control_id") or "").strip(): (r.get(col) or "").strip().upper()
                  for r in leer(D / "hoja_respuestas_stance.csv")}
    pendientes = [c for c in control if not respuestas.get(c["control_id"].strip())]
    hechos = [c for c in control if respuestas.get(c["control_id"].strip())]

    lineas = [
        f"# {titulo}",
        "",
        explicacion,
        "",
        f"**Casos pendientes: {len(pendientes)}.** Marca UNA casilla por caso: cambia `[ ]` por `[x]`.",
        "",
        "---",
        "",
    ]
    for c in pendientes:
        cid = c["control_id"].strip()
        sufijo = "  ⚠️ (oración insuficiente: puedes marcar la última opción)" if cid in INSUFICIENTES else ""
        lineas.append(bloque(cid, c["idioma"], c["oracion"], "Marca una:", opciones))
        if sufijo:
            lineas.insert(len(lineas) - 3, sufijo)
    if hechos:
        lineas += ["## Ya respondidos por ti (no hace falta tocar)", "",
                   "| Caso | Tu respuesta |", "|---|---|"]
        for c in hechos:
            lineas.append(f"| {c['control_id'].strip()} | {respuestas[c['control_id'].strip()]} |")
        lineas.append("")

    (D / nombre).write_text("\n".join(lineas), encoding="utf-8")
    return len(pendientes)


def generar_protocolo() -> int:
    filas = [l.split("\t") for l in (D / "control_protocolo_12.tsv").read_text(encoding="utf-8-sig").splitlines()[1:] if l.strip()]
    inv = json.loads((PROJECT_ROOT / "data" / "corpus_v2" / "inventario_unicos.json").read_text(encoding="utf-8"))
    por_nombre = {r["doi_filename"]: r for r in inv["unicos"]}

    lineas = [
        "# Protocolo de las revisiones — busca las palabras en el texto",
        "",
        "No hay que interpretar nada: **marca las casillas de las palabras que veas** en el abstract o en la metodología.",
        "Si no ves ninguna, marca la casilla «no aparece ninguna».",
        "",
        "---",
        "",
    ]
    for c in filas:
        cid, idioma, archivo = c[0], c[1], c[2]
        rec = por_nombre.get(archivo, {})
        sect = rec.get("sections") or {}
        abstract = " ".join(((sect.get("abstract") or sect.get("abstract_alt") or ""))[:700].split())
        methods = " ".join((sect.get("methods") or "")[:900].split())
        lineas += [
            f"### {cid} ({idioma}) — `{archivo}`",
            "",
            f"**Abstract:** {abstract}",
            "",
            f"**Metodología:** {methods}",
            "",
            "**1) ¿Aparece alguna de estas guías de reporte?**",
            "- [ ] PRISMA 2020",
            "- [ ] PRISMA-ScR (para scoping reviews)",
            "- [ ] ENTREQ",
            "- [ ] MOOSE",
            "- [ ] STROBE",
            "- [ ] no aparece ninguna",
            "",
            "**2) ¿Aparece alguno de estos marcos de conducción?**",
            "- [ ] JBI / Joanna Briggs",
            "- [ ] Cochrane",
            "- [ ] Arksey y O'Malley",
            "- [ ] EPPI",
            "- [ ] no aparece ninguno",
            "",
            "**3) ¿Aparece alguno de estos tipos de síntesis?**",
            "- [ ] meta-análisis / metaanálisis",
            "- [ ] meta-síntesis",
            "- [ ] síntesis temática / análisis temático",
            "- [ ] mapeo / mapping",
            "- [ ] síntesis narrativa / revisión narrativa",
            "- [ ] no aparece ninguno",
            "",
            "---",
            "",
        ]
    (D / "RESPONDER_4_PROTOCOLO.md").write_text("\n".join(lineas), encoding="utf-8")
    return len(filas)


def main() -> None:
    n1 = generar_pregunta(
        "RESPONDER_1_ACUERDO.md",
        "Pregunta 1 de 3 — ¿Está de acuerdo o en desacuerdo con la obra que cita?",
        "Piensa SOLO en esto: el autor que escribe, ¿respalda la obra citada, la critica, "
        "o simplemente la menciona/informa sin opinar? No importa si el verbo es fuerte o débil.",
        "A_postura",
        [("a", "Está **de acuerdo** con la obra citada (respalda, confirma, corrobora)"),
         ("b", "Está **en desacuerdo** o la critica (refuta, cuestiona, contradice)"),
         ("c", "**No se pronuncia**: solo informa, describe, menciona o adopta el método"),
         ("d", "**No puedo decidir** con lo que hay en la oración")],
    )
    n2 = generar_pregunta(
        "RESPONDER_2_FUERZA.md",
        "Pregunta 2 de 3 — ¿Qué tan fuerte es la afirmación?",
        "Piensa SOLO en la fuerza del verbo, no en si está de acuerdo o no. "
        "«demuestra» es fuerte; «sugiere» es medio; «podría» es débil.",
        "B_certeza",
        [("a", "**Fuerte**: demuestra, prueba, establece, confirma taxativamente"),
         ("b", "**Media**: indica, muestra, señala, sugiere, apunta"),
         ("c", "**Débil**: podría, parece, tiende a, posiblemente, tal vez"),
         ("d", "**No hay ningún verbo valorable** (solo describe o reporta un hecho)"),
         ("e", "**No puedo decidir** con lo que hay en la oración")],
    )
    n3 = generar_pregunta(
        "RESPONDER_3_FUNCION.md",
        "Pregunta 3 de 3 — ¿Para qué sirve esa cita en el texto?",
        "Piensa SOLO en la función, no en si está de acuerdo o no.",
        "C_funcion",
        [("a", "**Informar** lo que otro hizo o dijo (reporta)"),
         ("b", "**Usar el método o instrumento** de otro (siguiendo a, adaptando la escala de)"),
         ("c", "**Señalar un vacío**: falta evidencia, no hay estudios, se desconoce"),
         ("d", "**Conceder y redefinir**: «si bien…, aunque…, no obstante…»"),
         ("e", "**Es la postura propia** del autor que escribe (nuestros resultados, este estudio)"),
         ("f", "**No puedo decidir** con lo que hay en la oración")],
    )
    n4 = generar_protocolo()

    print("FORMULARIOS GENERADOS (preguntas en español, solo casos pendientes)")
    print(f"  RESPONDER_1_ACUERDO.md   -> {n1} casos pendientes de postura")
    print(f"  RESPONDER_2_FUERZA.md    -> {n2} casos pendientes de certeza")
    print(f"  RESPONDER_3_FUNCION.md   -> {n3} casos pendientes de función")
    print(f"  RESPONDER_4_PROTOCOLO.md -> {n4} casos (búsqueda de palabras)")
    print()
    print("Cada caso se responde marcando UNA casilla: [ ] -> [x]")


if __name__ == "__main__":
    main()
