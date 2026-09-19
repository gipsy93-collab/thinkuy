"""Importa las casillas marcadas en los formularios RESPONDER_*.md.

Traduce las letras (a, b, c…) a los códigos canónicos, conserva lo ya respondido y escribe:
    pase1_postura.csv / pase2_certeza.csv / pase3_funcion.csv
    control_protocolo_12.tsv  (columnas R1_humano, R2_humano, R3_humano)

USO:
    python tools/importar_formularios.py
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
D = PROJECT_ROOT / "data" / "dataset_v4"

MAPA = {
    "RESPONDER_1_ACUERDO.md": {"a": "SUPPORT", "b": "CONFLICT", "c": "NEUTRAL", "d": "AMBIGUO"},
    "RESPONDER_2_FUERZA.md": {"a": "STRONG", "b": "MODERATE", "c": "WEAK", "d": "NO_DECLARADA", "e": "AMBIGUO"},
    "RESPONDER_3_FUNCION.md": {"a": "REPORT", "b": "METHOD_ADOPTION", "c": "GAP",
                               "d": "CONCESSION_REDEFINITION", "e": "OWN_CLAIM", "f": "AMBIGUO"},
}
COL = {"RESPONDER_1_ACUERDO.md": "A_postura",
       "RESPONDER_2_FUERZA.md": "B_certeza",
       "RESPONDER_3_FUNCION.md": "C_funcion"}

# Nombre canónico del pase que escribe cada formulario (debe coincidir con leer_pases())
PASE = {"RESPONDER_1_ACUERDO.md": "pase1_postura.csv",
        "RESPONDER_2_FUERZA.md": "pase2_certeza.csv",
        "RESPONDER_3_FUNCION.md": "pase3_funcion.csv"}

CAB_CASO = re.compile(r"^###\s+([A-Z]{2}-\d{2})\s*\(")
CASILLA = re.compile(r"^-\s*\[[xX]\]\s*\*\*([a-f])\*\*")

# Protocolo: texto de la casilla -> código canónico
R1_MAP = {"prisma 2020": "PRISMA_2020", "prisma-scr": "PRISMA_ScR", "entreng": "ENTREQ",
          "entreq": "ENTREQ", "moose": "MOOSE", "strobe": "STROBE", "no aparece ninguna": "NONE_DECLARED"}
R2_MAP = {"jbi": "JBI", "cochrane": "COCHRANE", "arksey": "ARKSEY_OMALLEY", "eppi": "EPPI",
          "no aparece ninguno": "NONE_DECLARED"}
R3_MAP = {"meta-análisis": "META_ANALYSIS", "metaanálisis": "META_ANALYSIS", "meta-síntesis": "META_SYNTHESIS",
          "síntesis temática": "THEMATIC_SYNTHESIS", "mapeo": "DESCRIPTIVE_MAPPING",
          "narrativa": "NARRATIVE", "no aparece ninguno": "NONE"}


def leer_csv(path: Path, delim: str = ",") -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delim))


def importar_pregunta(archivo: str) -> dict[str, str]:
    p = D / archivo
    if not p.exists():
        return {}
    mapa = MAPA[archivo]
    out: dict[str, str] = {}
    cid = None
    for linea in p.read_text(encoding="utf-8").splitlines():
        m = CAB_CASO.match(linea.strip())
        if m:
            cid = m.group(1)
            continue
        m2 = CASILLA.match(linea.strip())
        if m2 and cid:
            out[cid] = mapa.get(m2.group(1).lower(), "")
            cid = None
    return out


def importar_protocolo() -> dict[str, dict]:
    p = D / "RESPONDER_4_PROTOCOLO.md"
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    cid, seccion = None, ""
    for linea in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^###\s+([A-Z]-[A-Z]{2}-\d{2})\s*\(", linea.strip())
        if m:
            cid = m.group(1)
            out[cid] = {"R1": "", "R2": "", "R3": ""}
            seccion = ""
            continue
        if not cid:
            continue
        s = linea.strip()
        if s.startswith("**1)"):
            seccion = "R1"; continue
        if s.startswith("**2)"):
            seccion = "R2"; continue
        if s.startswith("**3)"):
            seccion = "R3"; continue
        m2 = re.match(r"^-\s*\[[xX]\]\s*(.+)$", s)
        if m2 and seccion:
            etiqueta = m2.group(1).strip().lower()
            tabla = {"R1": R1_MAP, "R2": R2_MAP, "R3": R3_MAP}[seccion]
            for clave, codigo in tabla.items():
                if clave in etiqueta:
                    out[cid][seccion] = codigo
                    break
    return out


def main() -> None:
    base = {(r.get("control_id") or "").strip(): r for r in leer_csv(D / "hoja_respuestas_stance.csv")}
    control = leer_csv(D / "control_36.tsv", delim="\t")

    total = {}
    for archivo in MAPA:
        respuestas = importar_pregunta(archivo)
        col = COL[archivo]
        total[col] = respuestas
        # fusionar con lo que ya había
        for cid, v in base.items():
            if cid not in respuestas and (base[cid].get(col) or "").strip():
                respuestas[cid] = base[cid][col].strip().upper()
        # escribir el pase con el nombre canónico
        with open(D / PASE[archivo], "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["control_id", "idioma", "oracion_resumida", col, "observacion"])
            for c in control:
                cid = c["control_id"].strip()
                o = " ".join((c["oracion"] or "").split())
                w.writerow([cid, c["idioma"], (o[:180] + "…") if len(o) > 180 else o,
                            respuestas.get(cid, ""), ""])

    proto = importar_protocolo()
    if proto:
        tsv = [l.split("\t") for l in (D / "control_protocolo_12.tsv").read_text(encoding="utf-8-sig").splitlines()]
        cab = tsv[0]
        if "R1_humano" not in cab:
            cab += ["R1_humano", "R2_humano", "R3_humano"]
        i1, i2, i3 = cab.index("R1_humano"), cab.index("R2_humano"), cab.index("R3_humano")
        nuevas = [cab]
        for fila in tsv[1:]:
            if not fila or not fila[0].strip():
                continue
            while len(fila) < len(cab):
                fila.append("")
            cid = fila[0].strip()
            p = proto.get(cid, {})
            fila[i1] = p.get("R1", "")
            fila[i2] = p.get("R2", "")
            fila[i3] = p.get("R3", "")
            nuevas.append(fila)
        with open(D / "control_protocolo_12.tsv", "w", encoding="utf-8", newline="") as fh:
            for fila in nuevas:
                fh.write("\t".join(fila) + "\n")

    print("IMPORTACIÓN DE FORMULARIOS")
    for archivo in MAPA:
        col = COL[archivo]
        n = sum(1 for v in total[col].values() if v)
        print(f"  {archivo:26} -> {n:2} casos respondidos ({col})")
    print(f"  RESPONDER_4_PROTOCOLO.md   -> {sum(1 for v in proto.values() if any(v.values())):2} casos respondidos")
    print()
    print("Siguiente: python tools/calcular_kappa.py")


if __name__ == "__main__":
    main()
