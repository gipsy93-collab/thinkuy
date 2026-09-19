"""Re-mide el control de protocolo SOBRE LOS CASOS ORIGINALES.

Problema que resuelve: al re-ejecutar el etiquetador de protocolo se regeneró también la
muestra de control, de modo que 8 de 12 casos cambiaron y las respuestas humanas —indexadas
por `P-xx-yy`— quedaron asociadas a otros artículos. Re-medir así sería inválido.

Este script:
  1. Recupera los 12 casos ORIGINALES desde `control_protocolo_12_ANOTAR.md`.
  2. Recupera las respuestas humanas desde `RESPONDER_4_PROTOCOLO.md`.
  3. Recalcula SOLO los valores de la regla (R1/R2/R3) con el etiquetador corregido.
  4. Reescribe `control_protocolo_12.tsv` con los mismos casos, las mismas respuestas y la
     regla nueva, listo para `calcular_kappa.py`.

USO:
    python tools/remedir_control_protocolo.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from etiquetador_protocolo import etiquetar  # noqa: E402
from importar_formularios import importar_protocolo  # noqa: E402

D = PROJECT_ROOT / "data" / "dataset_v4"
CAB = re.compile(r"^#{2,3}\s+(P-[A-Z]{2}-\d{2})\s+—\s+([A-Z]{2})\s+—\s+`?(.+?)`?\s*$")


def casos_originales() -> list[tuple[str, str, str]]:
    out = []
    for linea in (D / "control_protocolo_12_ANOTAR.md").read_text(encoding="utf-8").splitlines():
        m = CAB.match(linea.strip())
        if m:
            out.append((m.group(1), m.group(2), m.group(3).strip().strip("`")))
    return out


def main() -> None:
    casos = casos_originales()
    print(f"Casos originales recuperados: {len(casos)}")
    inv = json.loads((PROJECT_ROOT / "data" / "corpus_v2" / "inventario_unicos.json").read_text(encoding="utf-8"))
    por_nombre = {r["doi_filename"]: r for r in inv["unicos"]}
    humanos = importar_protocolo()
    print(f"Respuestas humanas recuperadas: {sum(1 for v in humanos.values() if any(v.values()))}")

    filas = []
    faltantes = []
    for cid, idioma, archivo in casos:
        rec = por_nombre.get(archivo)
        if not rec:
            faltantes.append((cid, archivo))
            continue
        lab = etiquetar(rec)
        h = humanos.get(cid, {})
        filas.append([
            cid, idioma, archivo,
            lab.get("R1_guia_reporte", ""), lab.get("R1_guia_reporte_origen", ""),
            lab.get("R2_marco_conduccion", ""), lab.get("R2_marco_conduccion_origen", ""),
            lab.get("R3_tipo_sintesis", ""), lab.get("R3_tipo_sintesis_origen", ""),
            h.get("R1", ""), h.get("R2", ""), h.get("R3", ""),
            "",
        ])

    cab = ["control_id", "idioma", "archivo", "R1", "R1_origen", "R2", "R2_origen", "R3", "R3_origen",
           "R1_humano", "R2_humano", "R3_humano", "nota"]
    with open(D / "control_protocolo_12.tsv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(cab)
        w.writerows(filas)

    print(f"Escrito control_protocolo_12.tsv con {len(filas)} filas (casos originales + regla nueva)")
    if faltantes:
        print("ALERTA: casos sin artículo en el corpus (no se pudieron recalcular):")
        for cid, a in faltantes:
            print(f"   {cid}: {a}")


if __name__ == "__main__":
    main()
