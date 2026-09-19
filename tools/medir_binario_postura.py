"""Mide si la pregunta BINARIA sobre postura es más tratable que la taxonomía de 3 clases.

Motivo: el κ de 0,100 en el eje A puede ser un problema de la TAXONOMÍA, no del modelo.
Si la pregunta se descompone en dos decisiones binarias —
    A1: ¿el autor que cita toma postura sobre la obra citada? (sí / no)
    A2: ¿es a favor o en contra?  (solo si A1 = sí)
— cada paso es más simple y, sobre todo, se puede medir REUTILIZANDO las anotaciones
existentes, sin pedirle al IP una ronda nueva.

USO:
    python tools/medir_binario_postura.py
SALIDA:
    data/dataset_v4/diagnostico_postura_binaria.json
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
D = PROJECT_ROOT / "data" / "dataset_v4"

CON_POSTURA = {"SUPPORT", "CONFLICT"}
SIN_POSTURA = {"NEUTRAL"}
VACIOS = {"", "AMBIGUO", "NONE", "NA"}


def leer_tsv(p: Path) -> list[dict]:
    lineas = p.read_text(encoding="utf-8-sig").splitlines()
    cab = lineas[0].split("\t")
    return [dict(zip(cab, l.split("\t"))) for l in lineas[1:] if l.strip()]


def kappa(pares: list[tuple[int, int]]) -> dict:
    n = len(pares)
    if n == 0:
        return {"n": 0, "kappa": None, "po": None, "pe": None}
    po = sum(1 for a, b in pares if a == b) / n
    p1 = sum(1 for a, _ in pares if a == 1) / n
    p2 = sum(1 for _, b in pares if b == 1) / n
    pe = p1 * p2 + (1 - p1) * (1 - p2)
    k = (po - pe) / (1 - pe) if pe != 1 else 1.0
    return {"n": n, "kappa": round(k, 4), "po": round(po, 4), "pe": round(pe, 4),
            "regla_positivos": sum(1 for a, _ in pares if a == 1),
            "humano_positivos": sum(1 for _, b in pares if b == 1)}


def main() -> None:
    # La regla se lee del control vigente; las marcas humanas, del PASE (fuente autoritativa).
    filas = leer_tsv(D / "control_36.tsv")
    humanas: dict[str, str] = {}
    pase = D / "pase1_postura.csv"
    if pase.exists():
        with open(pase, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                humanas[(r.get("control_id") or "").strip()] = (r.get("A_postura") or "").strip().upper()
    if not humanas:
        humanas = {r["control_id"].strip(): (r.get("A_humano") or "").strip().upper() for r in filas}

    a1, a2 = [], []
    tabla_a1 = Counter()
    for r in filas:
        cid = r["control_id"].strip()
        regla = (r.get("A_regla") or "").strip().upper()
        hum = humanas.get(cid, "")
        if hum in VACIOS or regla in VACIOS:
            continue
        rb = 1 if regla in CON_POSTURA else 0
        hb = 1 if hum in CON_POSTURA else 0
        a1.append((rb, hb))
        tabla_a1[f"regla={'postura' if rb else 'sin postura'} | humano={'postura' if hb else 'sin postura'}"] += 1
        # A2: dirección, solo donde ambos ven postura
        if rb == 1 and hb == 1:
            a2.append((1 if regla == "SUPPORT" else 0, 1 if hum == "SUPPORT" else 0))

    res = {
        "A1_pregunta_binaria_hay_postura": kappa(a1),
        "A1_tabla_contingencia": dict(tabla_a1),
        "A2_direccion_solo_donde_coinciden": kappa(a2),
        "nota": "A1 se calcula reutilizando las anotaciones existentes; A2 mide el acuerdo de dirección "
                "en el subconjunto donde ambos detectan postura.",
    }
    (D / "diagnostico_postura_binaria.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 74)
    print("¿ES MÁS TRATABLE LA PREGUNTA BINARIA? (reutilizando las anotaciones del IP)")
    print("=" * 74)
    b = res["A1_pregunta_binaria_hay_postura"]
    print(f"\nA1 «¿hay postura?» (sí/no)   n={b['n']}  κ={b['kappa']}  acuerdo={b['po']}")
    print(f"   la regla marca postura en {b['regla_positivos']} casos; el IP en {b['humano_positivos']}")
    for k, v in res["A1_tabla_contingencia"].items():
        print(f"   {k}: {v}")
    d = res["A2_direccion_solo_donde_coinciden"]
    print(f"\nA2 «¿a favor o en contra?»   n={d['n']}  κ={d['kappa']}  acuerdo={d['po']}")
    print("\nComparación: la taxonomía de 3 clases daba κ = 0,100 con n=34.")
    print(f"Salida: {D / 'diagnostico_postura_binaria.json'}")
    print("=" * 74)


if __name__ == "__main__":
    main()
