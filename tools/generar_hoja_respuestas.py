"""Genera hojas de respuestas simplificadas para el Gate 2.

El TSV original mezcla columnas de la regla y del anotador y es incómodo de llenar.
Estas hojas tienen UNA FILA POR CASO y solo las celdas que el investigador debe llenar.
Se guardan con BOM (utf-8-sig) para que Excel respete los acentos.

USO:
    python tools/generar_hoja_respuestas.py
SALIDAS:
    data/dataset_v4/hoja_respuestas_stance.csv      (36 filas)
    data/dataset_v4/hoja_respuestas_protocolo.csv   (12 filas)
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
D = PROJECT_ROOT / "data" / "dataset_v4"


def leer_tsv(path: Path) -> list[list[str]]:
    lineas = path.read_text(encoding="utf-8-sig").splitlines()
    return [l.split("\t") for l in lineas[1:] if l.strip()]


def hoja_stance() -> int:
    filas = leer_tsv(D / "control_36.tsv")
    salida = D / "hoja_respuestas_stance.csv"
    with open(salida, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["control_id", "idioma", "oracion_resumida", "A_postura", "B_certeza", "C_funcion", "nota"])
        for c in filas:
            if len(c) < 3:
                continue
            oracion = " ".join(c[2].split())
            w.writerow([c[0], c[1], (oracion[:150] + "…") if len(oracion) > 150 else oracion, "", "", "", ""])
    return len(filas)


def hoja_protocolo() -> int:
    filas = leer_tsv(D / "control_protocolo_12.tsv")
    salida = D / "hoja_respuestas_protocolo.csv"
    with open(salida, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["control_id", "idioma", "archivo", "R1_guia_reporte", "R2_marco_conduccion", "R3_tipo_sintesis", "nota"])
        for c in filas:
            if len(c) < 3:
                continue
            w.writerow([c[0], c[1], c[2], "", "", "", ""])
    return len(filas)


def main() -> None:
    n1 = hoja_stance()
    n2 = hoja_protocolo()
    print(f"Hoja de respuestas STANCE   : {n1} filas -> {D / 'hoja_respuestas_stance.csv'}")
    print(f"Hoja de respuestas PROTOCOLO: {n2} filas -> {D / 'hoja_respuestas_protocolo.csv'}")
    print("\nLlena SOLO las columnas A_postura, B_certeza, C_funcion (y nota si quieres).")
    print("Una fila = un caso. Tres marcas por caso.")


if __name__ == "__main__":
    main()
