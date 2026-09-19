"""Verifica que la muestra de control de protocolo no haya cambiado entre rondas.

Si los casos cambian, las respuestas humanas (indexadas por `P-xx-yy`) quedan asociadas a
otro artículo y la re-medición sería inválida. Este control es obligatorio antes de
recorrer el kappa.

USO:
    python tools/verificar_control_protocolo.py
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
D = PROJECT_ROOT / "data" / "dataset_v4"

CAB = re.compile(r"^#{2,3}\s+(P-[A-Z]{2}-\d{2})\s+—\s+[A-Z]{2}\s+—\s+`?(.+?)`?\s*$")


def main() -> None:
    anotado = {}
    for linea in (D / "control_protocolo_12_ANOTAR.md").read_text(encoding="utf-8").splitlines():
        m = CAB.match(linea.strip())
        if m:
            anotado[m.group(1)] = m.group(2).strip().strip("`")
    actual = {}
    for r in csv.DictReader(open(D / "control_protocolo_12.tsv", encoding="utf-8-sig", newline=""), delimiter="\t"):
        actual[r["control_id"]] = r["archivo"]

    print(f"{'id':9} {'ANOTAR (v1, lo anotado)':44} {'TSV (v2, actual)':44} igual")
    iguales = 0
    for k in sorted(actual):
        a, b = anotado.get(k, ""), actual.get(k, "")
        ok = a == b
        iguales += int(ok)
        print(f"{k:9} {a[:42]:44} {b[:42]:44} {'SI' if ok else 'NO'}")
    print(f"\nCoinciden: {iguales}/{len(actual)}")
    if iguales < len(actual):
        print("ALERTA: los casos cambiaron. Hay que reconstruir la muestra desde ANOTAR antes de medir.")


if __name__ == "__main__":
    main()
