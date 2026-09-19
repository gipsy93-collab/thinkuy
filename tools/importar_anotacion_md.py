"""Importa la anotacion humana escrita a mano en control_36_CIEGO.md.

Preserva el trabajo del investigador y lo normaliza a JSON + CSV. Tolera:
  * espacios y comillas invertidas dentro de los valores (`__SUPPORT_`, `_REPORT__`)
  * variantes ortograficas (REPPORT -> REPORT, METHOD ADOPTATION -> METHOD_ADOPTION)
  * celdas vacias y notas libres
No inventa valores: lo que quedo vacio se reporta como vacio.

USO:
    python tools/importar_anotacion_md.py
SALIDAS:
    data/dataset_v4/anotacion_humana_stance.jsonl
    data/dataset_v4/anotacion_humana_stance.csv
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
D = PROJECT_ROOT / "data" / "dataset_v4"
FUENTE = D / "control_36_CIEGO.md"

VALORES_VALIDOS = {
    "SUPPORT", "CONFLICT", "NEUTRAL", "AMBIGUO",
    "STRONG", "MODERATE", "WEAK", "NO_DECLARADA",
    "REPORT", "METHOD_ADOPTION", "GAP", "CONCESSION_REDEFINITION", "OWN_CLAIM",
}

NORMALIZAR = {
    "REPPORT": "REPORT", "REPORTE": "REPORT", "REPOT": "REPORT",
    "METHOD ADOPTION": "METHOD_ADOPTION", "METHOD ADOPTATION": "METHOD_ADOPTION",
    "METHODADOPTION": "METHOD_ADOPTION", "METODOLOGIA": "METHOD_ADOPTION",
    "CONCESION_REDEFINICION": "CONCESSION_REDEFINITION",
    "CONCESSION": "CONCESSION_REDEFINITION",
}

CABECERA = re.compile(r"^##\s+([A-Z]{2}-\d{2})\s+—\s+([A-Z]{2})\s*$")
LINEA = re.compile(r"\*\*Tu etiqueta:\*\*\s*A=`([^`]*)`\s*·\s*B=`([^`]*)`\s*·\s*C=`([^`]*)`\s*·\s*nota:\s*(.*)$")


def limpiar(valor: str) -> str:
    v = (valor or "").strip().strip("`").strip()
    v = re.sub(r"^[_\.\s]+|[_\.\s]+$", "", v).strip()
    v = re.sub(r"\s+", " ", v).upper()
    if not v:
        return ""
    return NORMALIZAR.get(v, v)


def main() -> None:
    texto = FUENTE.read_text(encoding="utf-8")
    casos: list[dict] = []
    actual: dict | None = None
    for linea in texto.splitlines():
        m = CABECERA.match(linea.strip())
        if m:
            if actual:
                casos.append(actual)
            actual = {"control_id": m.group(1), "idioma_pedido": m.group(2), "A": "", "B": "", "C": "", "nota": ""}
            continue
        if actual:
            m2 = LINEA.match(linea.strip())
            if m2:
                actual["A"] = limpiar(m2.group(1))
                actual["B"] = limpiar(m2.group(2))
                actual["C"] = limpiar(m2.group(3))
                actual["nota"] = re.sub(r"\s+", " ", m2.group(4)).strip(" _")
    if actual:
        casos.append(actual)

    invalidos = []
    for c in casos:
        for eje in ("A", "B", "C"):
            v = c[eje]
            if v and v not in VALORES_VALIDOS:
                invalidos.append({"control_id": c["control_id"], "eje": eje, "valor": v})
                c[eje + "_crudo"] = v
                c[eje] = ""

    with open(D / "anotacion_humana_stance.jsonl", "w", encoding="utf-8") as fh:
        for c in casos:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    with open(D / "anotacion_humana_stance.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["control_id", "idioma_pedido", "A", "B", "C", "nota"])
        for c in casos:
            w.writerow([c["control_id"], c["idioma_pedido"], c["A"], c["B"], c["C"], c["nota"]])

    con_a = sum(1 for c in casos if c["A"])
    con_b = sum(1 for c in casos if c["B"])
    con_c = sum(1 for c in casos if c["C"])
    completos = sum(1 for c in casos if c["A"] and c["B"] and c["C"])
    con_nota = sum(1 for c in casos if c["nota"])
    print(f"Casos leidos            : {len(casos)}")
    print(f"Con marca en A          : {con_a}")
    print(f"Con marca en B          : {con_b}")
    print(f"Con marca en C          : {con_c}")
    print(f"Con las TRES marcas     : {completos}")
    print(f"Con nota libre          : {con_nota}")
    print(f"Valores no reconocidos  : {len(invalidos)}")
    for i in invalidos:
        print(f"   {i['control_id']} eje {i['eje']}: {i['valor']!r}")
    print(f"\nSalida: {D / 'anotacion_humana_stance.jsonl'}")


if __name__ == "__main__":
    main()
