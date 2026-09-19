"""Comparación por lotes de extractores de metadatos sobre páginas reales.

Mide, campo por campo y sobre N páginas:

  VÍA A  — determinista (meta etiquetas citation_* + JSON-LD), sin modelo.
  VÍA B1 — LLM dirigido por esquema: `schematron-3b` (especializado).
  VÍA B2 — LLM dirigido por esquema: `qwen2.5-coder-7b-instruct` (generalista).

Métricas (no requieren patrón dorado manual):
  * COBERTURA: en cuántas páginas cada vía devuelve el campo no vacío.
  * ACUERDO con la meta etiqueta (cuando existe): similitud normalizada.
  * FALLOS DE IDENTIFICADOR: DOI vacío o distinto (el campo crítico del pipeline).

USO:
    python tools/comparar_extractores.py --paginas data/demo/paginas_prueba.txt --max 12
SALIDA:
    data/demo/comparacion_lote.json  +  resumen en consola
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import httpx  # noqa: E402

from probar_schematron import (  # noqa: E402
    UA, ESQUEMA, estimar_tokens, json_ld_de, limpiar_html, meta_de, pedir_al_llm, reducir_a_contenido,
)

MODELOS = {
    "sch3b": "schematron-3b",
    "sch8b": "schematron-8b-i1",
    "qwen7b": "qwen2.5-coder-7b-instruct",
}
VIAS = ("meta", "sch3b", "sch8b", "qwen7b")
CAMPOS = ["titulo", "autores", "anio", "revista", "doi", "idioma", "resumen", "palabras_clave"]


def norm(t) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(t or "")) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def similitud(a, b) -> float:
    """Similitud por conjuntos de tokens (Jaccard) — tolera variantes menores."""
    ta, tb = set(norm(a).split()), set(norm(b).split())
    if not ta or not tb:
        return 0.0
    return round(len(ta & tb) / len(ta | tb), 3)


def vacio(v) -> bool:
    return v in (None, "", []) or (isinstance(v, str) and not v.strip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paginas", default="data/demo/paginas_prueba.txt")
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--solo-modelo", default="", help="Evalúa solo esa clave de MODELOS (una pasada por modelo)")
    args = ap.parse_args()

    modelos = {args.solo_modelo: MODELOS[args.solo_modelo]} if args.solo_modelo in MODELOS else MODELOS
    vias = ("meta",) + tuple(modelos.keys())

    lista = PROJECT_ROOT / args.paginas
    urls = [l.strip() for l in lista.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")][: args.max]
    print(f"Páginas a comparar: {len(urls)}")

    dir_html = PROJECT_ROOT / "data" / "demo" / "html"
    dir_html.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=60.0)

    resultados = []
    nombre_json = f"comparacion_lote_{args.solo_modelo}.json" if args.solo_modelo else "comparacion_lote.json"
    ruta_json = PROJECT_ROOT / "data" / "demo" / nombre_json

    def volcar(parcial: list[dict]) -> None:
        """Guardado incremental: una interrupción no debe perder las páginas ya hechas."""
        ruta_json.write_text(json.dumps({"n_paginas": len(parcial), "vias": list(vias),
                                         "parcial": True, "detalle": parcial},
                                        ensure_ascii=False, indent=2), encoding="utf-8")

    for i, url in enumerate(urls, 1):
        print(f"\n[{i:02d}/{len(urls)}] {url[:90]}")
        destino = dir_html / (re.sub(r"\W+", "_", url)[-70:] + ".html")
        if destino.exists():
            html_texto = destino.read_text(encoding="utf-8", errors="replace")
            print("   HTML en caché local")
        else:
            try:
                r = client.get(url)
                if r.status_code >= 400:
                    print(f"   HTTP {r.status_code}: se omite")
                    continue
                html_texto = r.text
                destino.write_text(html_texto, encoding="utf-8")
            except Exception as e:
                print(f"   fallo de red: {type(e).__name__}")
                continue

        reducido = reducir_a_contenido(limpiar_html(html_texto))
        print(f"   HTML reducido: {len(reducido)} bytes (~{estimar_tokens(reducido)} tokens)")
        fila = {"url": url, "meta": meta_de(html_texto), "ld": json_ld_de(html_texto)}
        fila["meta"].update({k: v for k, v in fila["ld"].items() if k.startswith("ld_")})

        for nombre, modelo in modelos.items():
            t0 = time.time()
            try:
                salida = pedir_al_llm(reducido, modelo)
                fila[nombre] = salida or {}
                fila[f"{nombre}_error"] = "" if salida else "SIN_RESPUESTA_PARSEABLE"
            except Exception as e:
                fila[nombre] = {}
                fila[f"{nombre}_error"] = type(e).__name__
                print(f"   {nombre:11} ERROR {type(e).__name__}")
            fila[f"{nombre}_segundos"] = round(time.time() - t0, 1)
            print(f"   {nombre:11} {fila[f'{nombre}_segundos']:6.1f}s  "
                  f"vacíos: {[c for c in CAMPOS if vacio(fila[nombre].get(c))] or 'ninguno'}"
                  + (f"  err={fila[f'{nombre}_error']}" if fila.get(f"{nombre}_error") else ""))
        print(f"   meta        campos vacíos: {[c for c in CAMPOS if vacio(fila['meta'].get(c))] or 'ninguno'}")
        resultados.append(fila)
        volcar(resultados)

    # ── Agregados ──
    cobertura: dict[str, dict[str, int]] = {v: defaultdict(int) for v in vias}
    acuerdo: dict[str, list[float]] = defaultdict(list)
    doi_fallos: dict[str, int] = defaultdict(int)
    segundos: dict[str, list[float]] = defaultdict(list)
    errores: dict[str, int] = defaultdict(int)
    for f in resultados:
        for via in vias:
            for c in CAMPOS:
                if not vacio(f[via].get(c)):
                    cobertura[via][c] += 1
            if via != "meta" and f.get(f"{via}_segundos") is not None:
                segundos[via].append(f[f"{via}_segundos"])
            if via != "meta" and f.get(f"{via}_error"):
                errores[via] += 1
            if not vacio(f["meta"].get("doi")) and via != "meta" and not f.get(f"{via}_error"):
                obtenido = str(f[via].get("doi") or "")
                if norm(obtenido) != norm(f["meta"]["doi"]):
                    doi_fallos[via] += 1
            for c in ("titulo", "resumen"):
                if via != "meta" and not f.get(f"{via}_error") and not vacio(f["meta"].get(c)) \
                        and not vacio(f[via].get(c)):
                    acuerdo[via].append(similitud(f["meta"][c], f[via][c]))

    salida = {
        "n_paginas": len(resultados),
        "vias": list(vias),
        "cobertura": {v: dict(cobertura[v]) for v in cobertura},
        "doi_fallos_respecto_a_meta": dict(doi_fallos),
        "similitud_media_con_meta": {k: round(sum(v) / len(v), 3) if v else None for k, v in acuerdo.items()},
        "segundos_promedio": {k: round(sum(v) / len(v), 1) if v else None for k, v in segundos.items()},
        "errores_por_via": dict(errores),
        "detalle": resultados,
    }
    nombre_json = f"comparacion_lote_{args.solo_modelo}.json" if args.solo_modelo else "comparacion_lote.json"
    (PROJECT_ROOT / "data" / "demo" / nombre_json).write_text(
        json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "=" * 84)
    print(f"COMPARACIÓN POR LOTES — {len(resultados)} páginas" + (f" · solo {args.solo_modelo}" if args.solo_modelo else ""))
    print("=" * 84)
    print(f"{'campo':16} " + " ".join(f"{v:>12}" for v in vias))
    for c in CAMPOS:
        print(f"{c:16} " + " ".join(f"{cobertura[v][c]:>12}" for v in vias))
    print(f"\nDOI distinto o vacío respecto a la meta etiqueta: {dict(doi_fallos)}")
    print(f"Similitud media con la meta etiqueta (título+resumen): {salida['similitud_media_con_meta']}")
    print(f"Segundos promedio por página: {salida['segundos_promedio']}")
    print(f"Errores por vía: {salida['errores_por_via']}")
    print(f"\nDetalle: data/demo/{nombre_json}")


if __name__ == "__main__":
    main()
