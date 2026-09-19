"""Diagnostico determinista del eje T1: distribucion de roles metodologicos (Fase 3).

Mide con marcadores estructurales si el corpus permite aprender la taxonomia de 5 roles
(SEMINAL / SYNTHESIS_REVIEW / THEORETICAL_FRAMEWORK / METHODOLOGICAL / EMPIRICAL) o si
el corpus es tan homogeneo que el colapso de clase es inevitable.

USO:
    python tools/diagnostico_t1_roles.py
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORPUS_V2 = PROJECT_ROOT / "data" / "corpus_v2"
OUT = PROJECT_ROOT / "data" / "dataset_v4"


def norm(t: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


REGLAS = [
    ("METHODOLOGICAL", [
        "validacion de", "validacion del", "propiedades psicometricas", "escala de", "escala validada",
        "instrumento", "diseño y validacion", "validacao de", "propriedades psicometricas",
        "instrument development", "psychometric", "validation of the", "scale development",
    ]),
    ("SEMINAL", [
        "seminal", "pionero", "pioneering", "fundacional", "foundational", "clasico", "obra de referencia",
        "seminal work", "first to propose",
    ]),
    ("THEORETICAL_FRAMEWORK", [
        "ensayo", "reflexion teorica", "marco conceptual", "propuesta teorica", "revision narrativa",
        "conceptual framework", "theoretical framework", "ensaio", "reflexao teorica",
        "estudio teorico", "analisis conceptual", "discusion teorica",
    ]),
    ("SYNTHESIS_REVIEW", [
        "revision sistematica", "scoping review", "revision de alcance", "meta-analisis", "metaanalisis",
        "prisma", "revision integrativa", "revision de la literatura", "revision bibliografica",
        "revisao sistematica", "revisao integrativa", "revisao de escopo", "systematic review",
        "literature review", "umbrella review", "rapid review", "mapeo sistematico",
        "scoping", "sintesis de evidencia", "overview of reviews",
    ]),
    ("EMPIRICAL", [
        "muestra de", "se aplico una encuesta", "cuestionario a", "estudio transversal", "estudio de cohorte",
        "ensayo clinico", "experimento", "datos primarios", "se recolectaron datos", "trabajo de campo",
        "amostra de", "ensaio clinico", "dados primarios", "cross-sectional study", "randomized",
        "survey of", "cohort study",
    ]),
]


def clasificar(texto: str) -> str:
    n = norm(texto)
    for rol, marcadores in REGLAS:
        if any(m in n for m in marcadores):
            return rol
    return "AMBIGUO"


def main() -> None:
    inv = json.loads((CORPUS_V2 / "inventario_unicos.json").read_text(encoding="utf-8"))
    conteo = Counter()
    por_idioma: dict[str, Counter] = {}
    sin_abstract = 0
    for rec in inv["unicos"]:
        if not rec["usabilidad"]["T1"]:
            sin_abstract += 1
            continue
        sect = rec.get("sections") or {}
        abstract = (sect.get("abstract") or sect.get("abstract_alt") or "").strip()
        rol = clasificar(abstract)
        conteo[rol] += 1
        por_idioma.setdefault(rec["idioma"], Counter())[rol] += 1

    total = sum(conteo.values())
    informe = {
        "articulos_T1": total,
        "articulos_sin_abstract": sin_abstract,
        "distribucion_roles": dict(conteo.most_common()),
        "proporcion_maxima": round(max(conteo.values()) / total, 3) if total else 0,
        "por_idioma": {k: dict(v.most_common()) for k, v in por_idioma.items()},
        "veredicto": (
            "COLAPSO DE CLASE: el corpus es homogeneo; la taxonomia de 5 roles no es aprendible tal cual"
            if total and max(conteo.values()) / total > 0.6 else
            "DISTRIBUCION UTILIZABLE"
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "diagnostico_t1_roles.json").write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print("DIAGNOSTICO DEL EJE T1 (roles metodologicos)")
    print("=" * 78)
    print(f"Articulos con abstract utilizable: {total}")
    for rol, n in conteo.most_common():
        print(f"  {rol:24} {n:4}  ({n/total*100:5.1f} %)")
    print(f"\nProporcion de la clase mayoritaria: {informe['proporcion_maxima']*100:.1f} %")
    print(f"VEREDICTO: {informe['veredicto']}")
    print(f"\nPor idioma: {json.dumps(informe['por_idioma'], ensure_ascii=False)}")
    print("=" * 78)


if __name__ == "__main__":
    main()
