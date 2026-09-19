"""Reconstruye la muestra de control PRESERVANDO los casos ya anotados por el investigador.

Estrategia: en lugar de regenerar la muestra y buscar coincidencias después, se parte de
los casos ya anotados (que se conservan con su id y sus marcas) y solo se rellenan los
huecos —los 7 casos sin oración válida y los estratos incompletos— con casos nuevos del
pool ya filtrado por calidad.

USO:
    python tools/refrescar_control_36.py
SALIDAS:
    data/dataset_v4/control_36.tsv               (muestra final)
    data/dataset_v4/control_36_CIEGO.md          (con las marcas previas precargadas)
    data/dataset_v4/hoja_respuestas_stance.csv   (precargada)
    data/dataset_v4/control_continuidad.json     (trazabilidad)
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
D = PROJECT_ROOT / "data" / "dataset_v4"
POOL = PROJECT_ROOT / "data" / "dataset_v4"

CABECERA = re.compile(r"^##\s+([A-Z]{2}-\d{2})\s+—\s+([A-Z]{2})\s*$")
ORACION = re.compile(r"^\*\*Oración:\*\*\s*(.*)$")
V_OLD = re.compile(r"A=`([^`]*)`\s*·\s*B=`([^`]*)`\s*·\s*C=`([^`]*)`\s*·\s*nota:\s*(.*)$")
POR_IDIOMA = 12


def norm(t: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def limpiar(v: str) -> str:
    return re.sub(r"^[_\.\s]+|[_\.\s]+$", "", (v or "").strip().strip("`")).strip().upper()


def leer_anotado() -> list[dict]:
    """Recupera la anotación del IP desde el archivo de rescate (el CIEGO fue sobrescrito)."""
    p = D / "recuperacion_anotacion_18sep.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for c in data.get("casos", []):
        out.append({
            "control_id": c["control_id"],
            "idioma": c["idioma"],
            "oracion": c.get("oracion", ""),
            "A": limpiar(c.get("A", "")),
            "B": limpiar(c.get("B", "")),
            "C": limpiar(c.get("C", "")),
            "nota": c.get("nota", ""),
            "descartar": bool(c.get("descartar")),
        })
    return out


def clave(o: str, n: int = 60) -> str:
    """Clave de emparejamiento tolerante.

    Se eliminan TODOS los caracteres no alfanuméricos antes de comparar, porque la
    extracción de PDF introduce guiones y espacios espurios ("ins trumentos", "orga- nizing")
    que rompen una comparación literal.
    """
    s = norm(o)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s[:n]


def oracion_util(s: str) -> bool:
    """Mismo filtro que usa el etiquetador (importado para no divergir)."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    from etiquetador_determinista import oracion_util as _ou
    return _ou(s)[0]


def cargar_pool() -> list[dict]:
    filas: list[dict] = []
    for nombre in ("candidatos_senal.jsonl", "candidatos_reporte.jsonl", "cola_ambiguo.jsonl"):
        p = POOL / nombre
        if p.exists():
            for l in p.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    filas.append(json.loads(l))
    return filas


def main() -> None:
    anotados = leer_anotado()
    pool = cargar_pool()
    print(f"Casos anotados recuperados : {len(anotados)}")
    print(f"Filas del pool etiquetado  : {len(pool)}")

    # Índice del pool por prefijo de oración (el pool es la fuente autoritativa del texto)
    por_oracion: dict[str, dict] = {}
    for r in pool:
        por_oracion.setdefault(clave(r.get("oracion", "")), r)

    usados_oracion: set[str] = set()
    usados_parrafo: set[str] = set()
    finales: list[dict] = []
    conservados = 0
    descartados: list[dict] = []

    # 1. Conservar los casos anotados: oración válida, no descartados por el IP y presentes en el pool
    for a in anotados:
        k = clave(a["oracion"])
        if a["descartar"]:
            descartados.append({**a, "motivo": "descartado por el IP"})
            continue
        if not oracion_util(a["oracion"]):
            descartados.append({**a, "motivo": "oración no utilizable (filtro de calidad)"})
            continue
        reg = por_oracion.get(k)
        if not reg:
            descartados.append({**a, "motivo": "no hallado en el pool etiquetado"})
            continue
        ph = norm((reg.get("parrafo") or "")[:160])
        if k in usados_oracion or (ph and ph in usados_parrafo):
            descartados.append({**a, "motivo": "duplicado de oración o párrafo"})
            continue
        usados_oracion.add(k)
        if ph:
            usados_parrafo.add(ph)
        finales.append({
            "control_id": a["control_id"],
            "idioma": a["idioma"],
            "oracion": reg.get("oracion", a["oracion"]),
            "parrafo": reg.get("parrafo", ""),
            "autor_citado": reg.get("autor_citado"),
            "eje_A": reg.get("eje_A", "NA"),
            "eje_B": reg.get("eje_B", "NA"),
            "eje_C": reg.get("eje_C", "NA"),
            "agente": reg.get("agente", "NA"),
            "veredicto": reg.get("veredicto", "NA"),
            "A_humano": a["A"],
            "B_humano": a["B"],
            "C_humano": a["C"],
            "norma": a["nota"],
            "origen": "CONSERVADO",
        })
        conservados += 1

    print(f"Conservados                : {conservados}")
    print(f"Descartados                : {len(descartados)}")
    for d in descartados:
        print(f"   {d['control_id']}: {d['motivo']} | {(d['oracion'] or '')[:60]}…")

    print(f"Conservados                : {conservados}")
    print(f"Descartados (oración basura o duplicados): {len(descartados)}")
    for d in descartados:
        print(f"   {d['control_id']}: {(d['oracion'] or '(sin oración)')[:70]}…")

    # 2. Rellenar por idioma hasta 12 con estratificación por dificultad
    conteo = defaultdict(int)
    for f in finales:
        conteo[f["idioma"]] += 1

    def disponible(r: dict) -> bool:
        clave = norm(r.get("oracion", ""))[:90]
        ph = norm((r.get("parrafo") or "")[:160])
        return clave not in usados_oracion and (not ph or ph not in usados_parrafo)

    def tomar(cands: list[dict], idioma: str, n: int) -> int:
        puestos = 0
        for r in cands:
            if puestos >= n:
                break
            if r.get("idioma") != idioma or not disponible(r):
                continue
            clave = norm(r.get("oracion", ""))[:90]
            ph = norm((r.get("parrafo") or "")[:160])
            usados_oracion.add(clave)
            if ph:
                usados_parrafo.add(ph)
            finales.append({
                "control_id": None, "idioma": idioma, "oracion": r.get("oracion", ""),
                "parrafo": r.get("parrafo", ""), "autor_citado": r.get("autor_citado"),
                "eje_A": r.get("eje_A"), "eje_B": r.get("eje_B"), "eje_C": r.get("eje_C"),
                "agente": r.get("agente"), "veredicto": r.get("veredicto"),
                "A_humano": "", "B_humano": "", "C_humano": "", "norma": "",
                "origen": "NUEVO",
            })
            puestos += 1
        return puestos

    for idioma in ("ES", "PT", "EN"):
        faltan = POR_IDIOMA - conteo[idioma]
        if faltan <= 0:
            continue
        conflicto = [r for r in pool if r.get("eje_A") == "CONFLICT"]
        apoyo = [r for r in pool if r.get("eje_A") == "SUPPORT"]
        funcion = [r for r in pool if r.get("eje_C") in ("GAP", "METHOD_ADOPTION", "CONCESSION_REDEFINITION")]
        amb = [r for r in pool if r.get("veredicto") == "AMBIGUO"]
        facil = [r for r in pool if r.get("eje_A") == "NEUTRAL" and r.get("eje_C") == "REPORT"]
        puestos = 0
        for cands, cuota in ((conflicto, 3), (apoyo, 3), (funcion, 3), (amb, 2), (facil, faltan)):
            puestos += tomar(cands, idioma, min(cuota, faltan - puestos))
            if puestos >= faltan:
                break
        if puestos < faltan:
            puestos += tomar(pool, idioma, faltan - puestos)

    # 3. Reasignar ids por idioma respetando los conservados
    contador = defaultdict(int)
    for f in finales:
        if f["control_id"]:
            n = int(f["control_id"].split("-")[1])
            contador[f["idioma"]] = max(contador[f["idioma"]], n)
    for f in finales:
        if not f["control_id"]:
            contador[f["idioma"]] += 1
            f["control_id"] = f"{f['idioma']}-{contador[f['idioma']]:02d}"

    orden = {"ES": 0, "PT": 1, "EN": 2}
    finales.sort(key=lambda x: (orden.get(x["idioma"], 3), x["control_id"]))

    # 4. Escribir TSV (todos los campos aplanados: sin saltos de línea, para lectores simples)
    def flat(t: str, n: int | None = None) -> str:
        s = re.sub(r"\s+", " ", (t or "")).strip().replace("\t", " ")
        return s[:n] if n else s

    cab = ["control_id", "idioma", "oracion", "parrafo", "A_regla", "B_regla", "C_regla", "agente", "veredicto",
           "A_humano", "B_humano", "C_humano", "norma", "origen"]
    with open(D / "control_36.tsv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(cab)
        for f in finales:
            w.writerow([f["control_id"], f["idioma"], flat(f["oracion"]), flat(f["parrafo"], 900),
                        f["eje_A"], f["eje_B"], f["eje_C"], f["agente"], f["veredicto"],
                        f["A_humano"], f["B_humano"], f["C_humano"], flat(f["norma"]), f["origen"]])

    # 5. Hoja de respuestas precargada
    with open(D / "hoja_respuestas_stance.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["control_id", "idioma", "oracion_resumida", "A_postura", "B_certeza", "C_funcion", "nota"])
        for f in finales:
            o = " ".join(f["oracion"].split())
            w.writerow([f["control_id"], f["idioma"], (o[:150] + "…") if len(o) > 150 else o,
                        f["A_humano"], f["B_humano"], f["C_humano"], f["norma"]])

    # 6. CIEGO con formato de tres líneas y marcas precargadas
    lineas = [
        "# Control ciego — STANCE (36 casos)",
        "",
        "**Cada caso recibe TRES marcas: una por eje.** A, B y C son preguntas independientes,",
        "no una categoría con opciones dentro.",
        "",
        "Rellena las tres líneas de cada caso, después del signo `=`.",
        "Si dos valores del MISMO eje coexisten, aplica la tabla de prioridad del codebook (§1bis)",
        "y registra el segundo en `nota` como `+VALOR`.",
        "",
        f"Los {conservados} casos que ya habías marcado vienen **precargados** con tu decisión anterior:",
        "solo completa los ejes que faltan. Los casos nuevos están en blanco.",
        "",
        "---",
        "",
    ]
    for f in finales:
        marca = " (nuevo)" if f["origen"] == "NUEVO" else ""
        lineas += [
            f"## {f['control_id']} — {f['idioma']}{marca}",
            "",
            f"**Oración:** {f['oracion']}",
            "",
            f"**Contexto:** {(f['parrafo'] or '')[:700]}",
            "",
            "**Tu etiqueta:**",
            "",
            "```",
            f"A_postura  (SUPPORT | CONFLICT | NEUTRAL)            = {f['A_humano'] or '____'}",
            f"B_certeza  (STRONG | MODERATE | WEAK | NO_DECLARADA) = {f['B_humano'] or '____'}",
            f"C_funcion  (REPORT | METHOD_ADOPTION | GAP | CONCESSION_REDEFINITION | OWN_CLAIM) = {f['C_humano'] or '____'}",
            f"nota = {f['norma'] or '____'}",
            "```",
            "",
            "---",
            "",
        ]
    (D / "control_36_CIEGO.md").write_text("\n".join(lineas), encoding="utf-8")

    (D / "control_continuidad.json").write_text(json.dumps({
        "conservados": conservados,
        "descartados": [{"id": d["control_id"], "oracion": d["oracion"][:120]} for d in descartados],
        "nuevos": sum(1 for f in finales if f["origen"] == "NUEVO"),
        "por_idioma": dict(conteo),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nMuestra final: {len(finales)} casos — conservados {conservados}, nuevos {sum(1 for f in finales if f['origen'] == 'NUEVO')}")
    for idioma in ("ES", "PT", "EN"):
        n = sum(1 for f in finales if f["idioma"] == idioma)
        marcados = sum(1 for f in finales if f["idioma"] == idioma and (f["A_humano"] or f["B_humano"] or f["C_humano"]))
        print(f"  {idioma}: {n} casos ({marcados} con marca previa)")


if __name__ == "__main__":
    main()
