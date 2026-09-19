"""Calcula el kappa de Cohen del Gate 2 y aplica la regla de decision pre-registrada.

Lee las anotaciones humanas de:
    data/dataset_v4/control_36.tsv          (ejes A, B, C)
    data/dataset_v4/control_protocolo_12.tsv (ejes R1, R2, R3)

Regla pre-registrada: kappa >= 0,60 por eje -> el eje se conserva como target.
                      kappa <  0,60        -> el eje SALE del target y queda como metadato.

USO:
    python tools/calcular_kappa.py
SALIDAS:
    data/dataset_v4/gate2_resultado.json
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
D = PROJECT_ROOT / "data" / "dataset_v4"

UMBRAL = 0.60

# Sinónimos y normalización: la comparación NO debe fallar por mayúsculas ni por variantes
# equivalentes de la misma clase (defecto detectado al comparar PRISMA_ScR vs PRISMA_SCR
# y NONE vs NONE_DECLARED, que producían desacuerdos falsos).
ALIAS = {
    "PRISMA_SCR": "PRISMA_SCR", "PRISMA_2020": "PRISMA_2020",
    "NONE": "NONE_DECLARED", "NONE_DECLARED": "NONE_DECLARED",
    "NOT_DECLARED": "NONE_DECLARED", "NINGUNA": "NONE_DECLARED",
}


def canon(v: str) -> str:
    s = (v or "").strip().upper().replace(" ", "_")
    return ALIAS.get(s, s)


def leer_tsv(path: Path) -> list[dict]:
    lineas = path.read_text(encoding="utf-8-sig").splitlines()
    if not lineas:
        return []
    cab = lineas[0].split("\t")
    out = []
    for l in lineas[1:]:
        if not l.strip():
            continue
        c = l.split("\t")
        c += [""] * (len(cab) - len(c))
        out.append(dict(zip(cab, c)))
    return out


def kappa_cohen(pares: list[tuple[str, str]]) -> dict:
    n = len(pares)
    if n == 0:
        return {"n": 0, "kappa": None, "po": None, "pe": None, "matriz": {}, "desacuerdos": []}
    etiquetas = sorted({x for p in pares for x in p})
    po = sum(1 for a, b in pares if a == b) / n
    pe = sum(
        (sum(1 for a, _ in pares if a == l) / n) * (sum(1 for _, b in pares if b == l) / n)
        for l in etiquetas
    )
    k = (po - pe) / (1 - pe) if pe != 1 else 1.0
    matriz: dict[str, dict[str, int]] = {}
    for a, b in pares:
        matriz.setdefault(a, {}).setdefault(b, 0)
        matriz[a][b] += 1
    return {"n": n, "kappa": round(k, 4), "po": round(po, 4), "pe": round(pe, 4), "matriz": matriz}


def evaluar_eje(nombre: str, pares: list[tuple[str, str]], ids: list[str], humano_amb: int, total: int) -> dict:
    # Canonicalizar AMBOS lados antes de comparar
    pares = [(canon(a), canon(b)) for a, b in pares]
    r = kappa_cohen(pares)
    r["eje"] = nombre
    r["umbral"] = UMBRAL
    r["humano_ambiguo"] = humano_amb
    r["n_muestra"] = total
    # Validez: un kappa calculado sobre una submuestra parcial (auto-seleccionada por el
    # anotador al marcar solo algunos ejes) NO vale como resultado del Gate 2.
    r["validez"] = "GATE_2" if r["n"] >= 0.8 * total else "EXPLORATORIO_NO_VALIDO_PARA_EL_GATE"
    if r["kappa"] is None:
        r["decision"] = "SIN_DATOS"
    else:
        r["decision"] = "SE_CONSERVA" if r["kappa"] >= UMBRAL else "SALE_DEL_TARGET"
    r["desacuerdos"] = [
        {"id": i, "regla": a, "humano": b}
        for i, (a, b) in zip(ids, pares) if a != b
    ][:25]
    return r


def leer_csv(path: Path) -> list[dict]:
    lineas = path.read_text(encoding="utf-8-sig").splitlines()
    if not lineas:
        return []
    cab = lineas[0].split(",")
    out = []
    for l in lineas[1:]:
        if not l.strip():
            continue
        # CSV simple: respeta comillas dobles
        campos, buf, dentro = [], [], False
        for ch in l:
            if ch == '"':
                dentro = not dentro
            elif ch == "," and not dentro:
                campos.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
        campos.append("".join(buf))
        campos += [""] * (len(cab) - len(campos))
        out.append(dict(zip(cab, campos)))
    return out


def pares_desde_hoja(hoja: Path, tsv: Path, mapa: list[tuple[str, str, str]]) -> tuple[list[tuple[str, str]], list[str], int, int]:
    """Cruza la hoja de respuestas con los valores de la regla (tomados del TSV original)."""
    regla_por_id = {r.get("control_id", ""): r for r in leer_tsv(tsv)}
    humano = leer_csv(hoja) if hoja.exists() else []
    pares, ids, amb = [], [], 0
    for h in humano:
        cid = (h.get("control_id") or "").strip()
        reg = regla_por_id.get(cid, {})
        for col_h, col_r in mapa:
            hum = (h.get(col_h) or "").strip()
            if not hum:
                continue
            if hum.upper() == "AMBIGUO":
                amb += 1
                continue
            pares.append(((reg.get(col_r) or "").strip(), hum))
            ids.append(f"{cid}")
    return pares, ids, amb, len(humano)


def leer_pases() -> dict[str, dict]:
    """Lee los tres pases de anotación (una dimensión por archivo) y los une por control_id."""
    mapa: dict[str, dict] = {}
    for archivo, col in (("pase1_postura.csv", "A_postura"),
                         ("pase2_certeza.csv", "B_certeza"),
                         ("pase3_funcion.csv", "C_funcion")):
        p = D / archivo
        if not p.exists():
            continue
        for r in leer_csv(p):
            cid = (r.get("control_id") or "").strip()
            if not cid:
                continue
            e = mapa.setdefault(cid, {"control_id": cid, "observacion": (r.get("observacion") or "").strip()})
            e[col] = (r.get(col) or "").strip().upper()
            if not e["observacion"] and (r.get("observacion") or "").strip():
                e["observacion"] = r["observacion"].strip()
    return mapa


def leer_protocolo_md() -> dict[str, dict]:
    """Lee las casillas [x] de control_protocolo_12_ANOTAR.md."""
    p = D / "control_protocolo_12_ANOTAR.md"
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    actual: dict | None = None
    seccion = ""
    for linea in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+([A-Z]-[A-Z]{2}-\d{2})\s+—", linea.strip())
        if m:
            actual = {"control_id": m.group(1), "R1": "", "R2": "", "R3": ""}
            out[m.group(1)] = actual
            seccion = ""
            continue
        if not actual:
            continue
        if linea.strip().startswith("**R1"):
            seccion = "R1"
            continue
        if linea.strip().startswith("**R2"):
            seccion = "R2"
            continue
        if linea.strip().startswith("**R3"):
            seccion = "R3"
            continue
        m2 = re.search(r"\[x\]\s*([A-Z_]+)", linea, re.IGNORECASE)
        if m2 and seccion:
            actual[seccion] = m2.group(1).upper()
    return out


def main() -> None:
    resumen: dict = {"umbral": UMBRAL, "ejes": {}}

    hoja_s = D / "hoja_respuestas_stance.csv"
    hoja_p = D / "hoja_respuestas_protocolo.csv"

    # Prioridad 1: los tres pases (una dimensión por archivo), que es el formato que el IP usa
    pases = leer_pases()
    if pases:
        tsv = {r.get("control_id", ""): r for r in leer_tsv(D / "control_36.tsv")}
        for eje, col in (("A", "A_postura"), ("B", "B_certeza"), ("C", "C_funcion")):
            pares, ids, amb, excl = [], [], 0, 0
            for cid, e in pases.items():
                if e.get("observacion") == "ORACION_INSUFICIENTE":
                    excl += 1
                    continue
                hum = (e.get(col) or "").strip()
                if not hum:
                    continue
                if hum == "AMBIGUO":
                    amb += 1
                    continue
                regla = (tsv.get(cid, {}).get(f"{eje}_regla") or "").strip()
                pares.append((regla, hum))
                ids.append(cid)
            r = evaluar_eje(f"stance_{eje}", pares, ids, amb, len(pases) - excl)
            r["excluidos_por_oracion_insuficiente"] = excl
            resumen["ejes"][f"stance_{eje}"] = r
    elif hoja_s.exists():
        for eje, col_h, col_r in (("A", "A_postura", "A_regla"),
                                  ("B", "B_certeza", "B_regla"),
                                  ("C", "C_funcion", "C_regla")):
            pares, ids, amb, total = pares_desde_hoja(hoja_s, D / "control_36.tsv", [(col_h, col_r)])
            resumen["ejes"][f"stance_{eje}"] = evaluar_eje(f"stance_{eje}", pares, ids, amb, total)
    else:
        stance = leer_tsv(D / "control_36.tsv")
        for eje, col_regla, col_hum in (("A", "A_regla", "A_humano"),
                                        ("B", "B_regla", "B_humano"),
                                        ("C", "C_regla", "C_humano")):
            pares, ids, amb = [], [], 0
            for r in stance:
                regla = (r.get(col_regla) or "").strip()
                hum = (r.get(col_hum) or "").strip()
                if not hum:
                    continue
                if hum.upper() == "AMBIGUO":
                    amb += 1
                    continue
                pares.append((regla, hum))
                ids.append(r.get("control_id", "?"))
            resumen["ejes"][f"stance_{eje}"] = evaluar_eje(f"stance_{eje}", pares, ids, amb, len(stance))

    # El TSV tiene prioridad si ya contiene respuestas humanas (las escribe el importador);
    # si no, se leen las casillas del formulario ANOTAR.
    tsv_p = {r.get("control_id", ""): r for r in leer_tsv(D / "control_protocolo_12.tsv")}
    hay_humano_tsv = any((r.get("R1_humano") or r.get("R2_humano") or r.get("R3_humano")) for r in tsv_p.values())
    proto_md = {} if hay_humano_tsv else leer_protocolo_md()
    if hay_humano_tsv:
        for eje in ("R1", "R2", "R3"):
            pares, ids, amb = [], [], 0
            for cid, r in tsv_p.items():
                hum = (r.get(f"{eje}_humano") or "").strip()
                if not hum:
                    continue
                if hum.upper() == "AMBIGUO":
                    amb += 1
                    continue
                pares.append(((r.get(eje) or "").strip(), hum.upper()))
                ids.append(cid)
            resumen["ejes"][f"protocolo_{eje}"] = evaluar_eje(f"protocolo_{eje}", pares, ids, amb, len(tsv_p))
    elif proto_md:
        for eje in ("R1", "R2", "R3"):
            pares, ids, amb = [], [], 0
            for cid, e in proto_md.items():
                hum = (e.get(eje) or "").strip()
                if not hum:
                    continue
                if hum == "AMBIGUO":
                    amb += 1
                    continue
                regla = (tsv_p.get(cid, {}).get(eje) or "").strip()
                pares.append((regla, hum))
                ids.append(cid)
            resumen["ejes"][f"protocolo_{eje}"] = evaluar_eje(f"protocolo_{eje}", pares, ids, amb, len(proto_md))
    elif hoja_p.exists():
        for eje, col_h, col_r in (("R1", "R1_guia_reporte", "R1"),
                                  ("R2", "R2_marco_conduccion", "R2"),
                                  ("R3", "R3_tipo_sintesis", "R3")):
            pares, ids, amb, total = pares_desde_hoja(hoja_p, D / "control_protocolo_12.tsv", [(col_h, col_r)])
            resumen["ejes"][f"protocolo_{eje}"] = evaluar_eje(f"protocolo_{eje}", pares, ids, amb, total)
    else:
        proto = leer_tsv(D / "control_protocolo_12.tsv")
        for eje, col_regla, col_hum in (("R1", "R1", "R1_humano"),
                                        ("R2", "R2", "R2_humano"),
                                        ("R3", "R3", "R3_humano")):
            pares, ids, amb = [], [], 0
            for r in proto:
                regla = (r.get(col_regla) or "").strip()
                hum = (r.get(col_hum) or "").strip()
                if not hum:
                    continue
                if hum.upper() == "AMBIGUO":
                    amb += 1
                    continue
                pares.append((regla, hum))
                ids.append(r.get("control_id", "?"))
            resumen["ejes"][f"protocolo_{eje}"] = evaluar_eje(f"protocolo_{eje}", pares, ids, amb, len(proto))

    (D / "gate2_resultado.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print("GATE 2 — KAPPA DE COHEN POR EJE (umbral pre-registrado: >= 0,60)")
    print("=" * 78)
    sin_datos = 0
    for nombre, r in resumen["ejes"].items():
        if r["decision"] == "SIN_DATOS":
            sin_datos += 1
            print(f"\n{nombre:16} SIN ANOTACIONES (n={r['n_muestra']})")
            continue
        print(f"\n{nombre:16} n={r['n']}  kappa={r['kappa']}  acuerdo_observado={r['po']}  ->  {r['decision']}")
        if r["humano_ambiguo"]:
            print(f"                 (el anotador humano marcó AMBIGUO en {r['humano_ambiguo']} casos)")
        for a, destinos in r["matriz"].items():
            print(f"                 regla={a:26} -> {destinos}")
        if r["desacuerdos"]:
            print("                 primeros desacuerdos:")
            for d in r["desacuerdos"][:6]:
                print(f"                   {d['id']}: regla={d['regla']} humano={d['humano']}")
    if sin_datos == len(resumen["ejes"]):
        print("\nNo hay anotaciones todavía.")
        print("  Llena: data/dataset_v4/hoja_respuestas_stance.csv     (36 filas, columnas A_postura / B_certeza / C_funcion)")
        print("  Llena: data/dataset_v4/hoja_respuestas_protocolo.csv  (12 filas, columnas R1 / R2 / R3)")
    print(f"\nResultado: {D / 'gate2_resultado.json'}")
    print("=" * 78)


if __name__ == "__main__":
    main()
