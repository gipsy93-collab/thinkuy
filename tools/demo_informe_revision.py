"""Demostración end-to-end del pipeline DETERMINISTA sobre un área real del corpus.

No usa ningún modelo de lenguaje. Todo dato del informe es trazable al texto fuente:
los campos PCC son subcadenas literales y cada etiqueta de cita muestra el marcador
que la sustenta.

USO:
    python tools/demo_informe_revision.py [--area medicina-social]
SALIDA:
    data/demo/INFORME_REVISION_<area>.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from backend.radar.text_extractor import (  # noqa: E402
    extract_citation_contexts,
    extract_numeric_citation_contexts,
    parse_reference_entry,
)
from etiquetador_determinista import etiquetar as etiquetar_cita  # noqa: E402
from etiquetador_determinista import oracion_util  # noqa: E402
from etiquetador_protocolo import etiquetar as etiquetar_protocolo  # noqa: E402
from etiquetador_t2_pcc import NO_ESPECIFICADO, etiquetar as etiquetar_pcc  # noqa: E402

OUT_DIR = PROJECT_ROOT / "data" / "demo"
ETIQUETA_LEGIBLE = {
    "REPORT": "posible mención / reporte",
    "CONCESSION_REDEFINITION": "posible concesión o matización",
    "GAP": "posible vacío de conocimiento",
    "METHOD_ADOPTION": "posible adopción metodológica",
    "SUPPORT": "posible consenso",
    "CONFLICT": "posible disenso",
    "NEUTRAL": "sin postura comprometida",
    "STRONG": "certeza alta",
    "MODERATE": "certeza media",
    "WEAK": "certeza baja",
    "NO_DECLARADA": "certeza no declarada",
}


def legible(codigo: str) -> str:
    return ETIQUETA_LEGIBLE.get(codigo, codigo)


def corto(texto: str, n: int = 220) -> str:
    t = " ".join((texto or "").split())
    return (t[:n] + "…") if len(t) > n else t


def citas_de(rec: dict) -> list[dict]:
    sect = rec.get("sections") or {}
    cuerpo = "\n\n".join(v for k, v in sect.items() if k != "references" and v)
    if len(cuerpo) < 2000:
        return []
    refs = [parse_reference_entry(r) for r in (rec.get("references") or [])[:200]]
    refs = [r for r in refs if r and (r.get("author") or r.get("doi"))]
    vistos, salida = set(), []
    for pr in refs[:60]:
        for ctx in extract_citation_contexts(cuerpo, cited_doi=pr.get("doi") or "",
                                             cited_author=pr.get("author"), cited_year=pr.get("year")):
            k = " ".join((ctx.get("sentence") or "").split())[:70].lower()
            if k and k not in vistos:
                vistos.add(k)
                salida.append((ctx, pr))
    for ctx in extract_numeric_citation_contexts(cuerpo, rec.get("references") or []):
        k = " ".join((ctx.get("sentence") or "").split())[:70].lower()
        if k and k not in vistos:
            vistos.add(k)
            salida.append((ctx, {"author": ctx.get("cited_author"), "year": ctx.get("cited_year")}))
    return salida


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="medicina-social")
    ap.add_argument("--max-citas", type=int, default=3, help="Ejemplos de cita por artículo en el informe")
    args = ap.parse_args()

    inv = json.loads((PROJECT_ROOT / "data" / "corpus_v2" / "inventario_unicos.json").read_text(encoding="utf-8"))
    articulos = [x for x in inv["unicos"] if x["area"] == args.area]
    duplicados = [d for d in inv["duplicados"] if d.get("area") == args.area]
    if not articulos:
        print(f"No hay artículos en el área {args.area}")
        return

    lineas: list[str] = []
    lineas += [
        f"# Informe de revisión — área: {args.area}",
        "",
        "> **Generado sin ningún modelo de lenguaje.** Cada dato es trazable al texto fuente: los campos "
        "de la matriz son subcadenas literales y cada etiqueta de cita muestra el marcador que la sustenta.",
        "> La clasificación de postura se presenta como **«posible»** y en capa de **baja confianza** "
        "(κ humano 0,10-0,37): es una sugerencia para el investigador, no una decisión.",
        "",
    ]

    # ── 1. Flujo de selección ──
    n_unic = len(articulos)
    con_abs = sum(1 for x in articulos if (x.get("sections_meta") or {}).get("abstract"))
    con_met = sum(1 for x in articulos if (x.get("sections_meta") or {}).get("methods"))
    con_ref = sum(1 for x in articulos if (x.get("n_referencias") or 0) > 0)
    usable_t3 = sum(1 for x in articulos if x["usabilidad"]["T3"])
    usable_t2 = sum(1 for x in articulos if x["usabilidad"]["T2"])
    banderas = Counter(f for x in articulos for f in (x.get("flags") or []))
    idiomas = Counter(x["idioma"] for x in articulos)

    lineas += [
        "## 1. Flujo de selección del corpus",
        "",
        "| Etapa | n |",
        "| :--- | ---: |",
        f"| Documentos aportados (tras deduplicación por SHA-256) | **{n_unic}** |",
        f"| Copias duplicadas descartadas | {len(duplicados)} |",
        f"| Con sección de resumen legible | {con_abs} |",
        f"| Con sección de metodología legible | {con_met} |",
        f"| Con lista de referencias | {con_ref} |",
        f"| **Utilizables para auditoría de citas** | **{usable_t3}** |",
        f"| **Utilizables para matriz PCC** | **{usable_t2}** |",
        "",
        f"**Idiomas:** " + " · ".join(f"{k} {v}" for k, v in idiomas.most_common()),
        "",
        "**Bandera de calidad detectadas:** " + (", ".join(f"`{k}` {v}" for k, v in banderas.most_common()) or "ninguna"),
        "",
        "---",
        "",
    ]

    # ── 2. Protocolo declarado ──
    lineas += ["## 2. Protocolo declarado por cada revisión", "",
               "| Revisión | Idioma | R1 guía de reporte | R2 marco de conducción | R3 tipo de síntesis |",
               "| :--- | :---: | :--- | :--- | :--- |"]
    protocolos = {}
    for x in articulos:
        lab = etiquetar_protocolo(x)
        protocolos[x["doi_filename"]] = lab
        lineas.append(f"| `{x['doi_filename'][:38]}` | {x['idioma']} | {lab['R1_guia_reporte']} | "
                      f"{lab['R2_marco_conduccion']} | {lab['R3_tipo_sintesis']} |")
    lineas += ["", "---", ""]

    # ── 3. Matriz JBI PCC (verbatim) ──
    lineas += ["## 3. Matriz de extracción JBI PCC (fragmentos literales)", "",
               "> Cada celda es un **fragmento copiado del artículo**. Cuando el dato no consta, se declara. "
               "Nada se inventa ni se rellena.", ""]
    cobertura = Counter()
    matrices = {}
    for x in articulos:
        if not x["usabilidad"]["T2"]:
            continue
        lab = etiquetar_pcc(x.get("sections") or {})
        matrices[x["doi_filename"]] = lab
        for campo in ("poblacion", "concepto", "contexto", "diseno"):
            if lab[campo] != NO_ESPECIFICADO:
                cobertura[campo] += 1
        lineas += [f"### `{x['doi_filename'][:44]}` — {x['idioma']}", ""]
        for campo, etiq in (("poblacion", "Población"), ("concepto", "Concepto"),
                            ("contexto", "Contexto"), ("diseno", "Diseño")):
            val = lab[campo]
            fuente = lab[f"{campo}_fuente"]
            if val == NO_ESPECIFICADO:
                lineas.append(f"- **{etiq}:** *No especificado en la metodología*")
            else:
                lineas.append(f"- **{etiq}** (fuente: {fuente.lower()}): «{corto(val, 260)}»")
        lineas += ["", ""]
    lineas += ["**Cobertura de la matriz en esta área:** " +
               " · ".join(f"{c} {cobertura[c]}/{usable_t2}" for c in ("poblacion", "concepto", "contexto", "diseno")),
               "", "---", ""]

    # ── 4. Auditoría de citas con evidencia ──
    lineas += ["## 4. Auditoría de citas — sugerencias con la evidencia a la vista", "",
               "> La etiqueta es una **sugerencia**. Se muestra el marcador exacto que la activa para que el "
               "investigador pueda refutarla en un segundo. Las etiquetas usan la formulación «posible».", ""]
    total_citas = con_marcador = ambiguas = 0
    por_funcion = Counter()
    for x in articulos:
        if not x["usabilidad"]["T3"]:
            continue
        filas = []
        for ctx, pr in citas_de(x):
            oracion = ctx.get("sentence", "")
            util, _ = oracion_util(oracion)
            if not util:
                continue
            total_citas += 1
            lab = etiquetar_cita(oracion, ctx.get("paragraph", ""), ctx.get("section", "body"), pr.get("author"))
            if lab["veredicto"] == "AMBIGUO":
                ambiguas += 1
            else:
                por_funcion[lab["eje_C"]] += 1
            if lab["marcadores_A"] or lab["marcadores_C"] or lab["marcadores_concesion"]:
                con_marcador += 1
            filas.append((oracion, lab))
        if not filas:
            continue
        lineas += [f"### `{x['doi_filename'][:44]}` — {x['idioma']} ({len(filas)} citas analizadas)", ""]
        for oracion, lab in filas[: args.max_citas]:
            evidencia = []
            for eje, dicc in (("A", lab["marcadores_A"]), ("C", lab["marcadores_C"])):
                for valor, marcadores in dicc.items():
                    evidencia += [f"`{m}` → {legible(valor)}" for m in marcadores[:2]]
            for m in lab["marcadores_concesion"][:2]:
                evidencia.append(f"`{m}` → posible concesión o matización")
            if lab["marcadores_B"]:
                for valor, marcadores in lab["marcadores_B"].items():
                    evidencia.append(f"`{marcadores[0]}` → {legible(valor)} (certeza)")
            etiqueta = legible(lab["eje_C"]) if lab["veredicto"] != "AMBIGUO" else "sin decisión automática"
            lineas += [f"- **{etiqueta}** — «{corto(oracion, 200)}»",
                       f"  - evidencia: {'; '.join(evidencia) if evidencia else 'atribución explícita sin marcador evaluativo'}"]
        lineas += ["", ""]
    lineas += [
        "**Panel de cobertura de la auditoría de citas:**",
        "",
        "| Métrica | Valor |",
        "| :--- | ---: |",
        f"| Citas analizadas | {total_citas} |",
        f"| Con marcador explícito localizado | {con_marcador} ({con_marcador/max(total_citas,1)*100:.1f} %) |",
        f"| Derivadas a revisión humana por ambigüedad | {ambiguas} ({ambiguas/max(total_citas,1)*100:.1f} %) |",
        "",
        "**Distribución de funciones retóricas detectadas:** " +
        " · ".join(f"{legible(k)} {v}" for k, v in por_funcion.most_common()),
        "",
        "---",
        "",
    ]

    # ── 5. Vacíos de conocimiento ──
    vacios = []
    for x in articulos:
        if not x["usabilidad"]["T3"]:
            continue
        for ctx, pr in citas_de(x):
            oracion = ctx.get("sentence", "")
            util, _ = oracion_util(oracion)
            if not util:
                continue
            lab = etiquetar_cita(oracion, ctx.get("paragraph", ""), ctx.get("section", "body"), pr.get("author"))
            if lab["veredicto"] == "ASIGNADO" and lab["eje_C"] == "GAP":
                vacios.append((x["doi_filename"], oracion, lab["marcadores_C"].get("GAP", [])))
    lineas += [f"## 5. Vacíos de conocimiento detectados ({len(vacios)})", "",
               "> Cada vacío es una **oportunidad de investigación** y se cita literalmente. Es la materia prima "
               "de la justificación de una revisión de alcance.", ""]
    for doi, oracion, marcadores in vacios[:15]:
        lineas.append(f"- `{doi[:34]}` — «{corto(oracion, 240)}»  \n  - activado por: {', '.join(f'`{m}`' for m in marcadores[:3])}")
    if not vacios:
        lineas.append("- No se detectaron enunciados de vacío con marcador explícito en esta área.")
    lineas += ["", "---", ""]

    # ── 6. Límites declarados ──
    lineas += [
        "## 6. Límites de este informe (declarados, no ocultos)",
        "",
        "1. **Las etiquetas de cita son sugerencias.** La regla determinista no coincide con un anotador humano "
        "al nivel exigido (κ 0,10 en postura, 0,37 en función retórica). Se muestran como «posible» y con su "
        "marcador, para que el investigador decida.",
        "2. **La matriz PCC es literal pero no infalible en la selección.** El fragmento está garantizado como "
        "subcadena del texto, pero cuál fragmento *es* el correcto requiere ojo humano.",
        "3. **Los campos «No especificado» no son un error**: significan que el artículo no declara ese dato en "
        "las secciones leídas.",
        "4. **El protocolo declarado (R1/R2/R3) es la única capa de juicio que superó la validación humana**, "
        "y solo R1 (κ 0,654).",
        "5. **Ningún dato de este informe proviene de un modelo de lenguaje.**",
        "",
        f"*Generado por `tools/demo_informe_revision.py` sobre {n_unic} artículos del área `{args.area}`.*",
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    salida = OUT_DIR / f"INFORME_REVISION_{args.area}.md"
    salida.write_text("\n".join(lineas), encoding="utf-8")

    print("=" * 78)
    print(f"INFORME DE REVISIÓN — área {args.area}")
    print("=" * 78)
    print(f"Artículos únicos            : {n_unic} (idiomas: {dict(idiomas)})")
    print(f"Con abstract / métodos / refs: {con_abs} / {con_met} / {con_ref}")
    print(f"Utilizables T3 (citas)      : {usable_t3}   |  T2 (PCC): {usable_t2}")
    print(f"Citas analizadas            : {total_citas}")
    print(f"  con marcador explícito    : {con_marcador}")
    print(f"  derivadas a revisión      : {ambiguas}")
    print(f"Vacíos detectados           : {len(vacios)}")
    print(f"Cobertura PCC               : {dict(cobertura)}")
    print(f"\nInforme: {salida}")
    print("=" * 78)


if __name__ == "__main__":
    main()
