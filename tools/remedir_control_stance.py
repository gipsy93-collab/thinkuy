"""Re-mide el control de stance SOBRE LOS 36 CASOS ORIGINALES (los que el IP anotó).

Mismo problema que en protocolo: al re-ejecutar el etiquetador se regeneró la muestra de
control y los casos cambiaron, dejando las respuestas humanas pegadas a otras oraciones.
Este script recupera los 36 casos del snapshot, recalcula SOLO el valor de la regla con el
etiquetador corregido y reescribe `control_36.tsv` listo para `calcular_kappa.py`.

USO:
    python tools/remedir_control_stance.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from etiquetador_determinista import etiquetar  # noqa: E402

D = PROJECT_ROOT / "data" / "dataset_v4"


def main() -> None:
    snap = json.loads((D / "control_36_snapshot.json").read_text(encoding="utf-8"))
    print(f"Casos originales recuperados: {len(snap)}")

    filas = []
    for r in snap:
        lab = etiquetar(r.get("oracion", ""), r.get("parrafo", ""), "body", autor_citado=None)
        filas.append([
            r["control_id"], r["idioma"],
            " ".join((r.get("oracion") or "").split()),
            " ".join((r.get("parrafo") or "").split())[:900],
            lab["eje_A"], lab["eje_B"], lab["eje_C"], lab["agente"], lab["veredicto"],
            (r.get("A_humano") or "").strip().upper(),
            (r.get("B_humano") or "").strip().upper(),
            (r.get("C_humano") or "").strip().upper(),
            (r.get("norma") or "").strip(),
            "CONSERVADO",
        ])

    cab = ["control_id", "idioma", "oracion", "parrafo", "A_regla", "B_regla", "C_regla", "agente", "veredicto",
           "A_humano", "B_humano", "C_humano", "norma", "origen"]
    with open(D / "control_36.tsv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(cab)
        w.writerows(filas)

    from collections import Counter
    print("Regla nueva -> A:", dict(Counter(f[4] for f in filas)))
    print("Regla nueva -> B:", dict(Counter(f[5] for f in filas)))
    print("Regla nueva -> C:", dict(Counter(f[6] for f in filas)))
    print(f"Escrito control_36.tsv con {len(filas)} filas (casos originales + regla nueva)")


if __name__ == "__main__":
    main()
