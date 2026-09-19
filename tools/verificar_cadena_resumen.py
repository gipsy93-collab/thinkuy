"""Verificación de la cadena determinista del resumen sobre el lote de 15 páginas reales.

Comprueba, página por página, de dónde sale el resumen (o por qué queda vacío) usando
`radar.harvester.abstract_chain` — sin modelo. Contraste esperado, fijado en el Hito 38:

  * SciELO  -> `citation_abstract`
  * OJS 3   -> `dc_description` (OJS publica el resumen ahí, un valor por idioma)
  * Redalyc -> **vacío**: son fichas *stub* y sus PDF no contienen resumen (el 3B se lo
    inventaba; esa es exactamente la conducta que la cadena debe impedir).

USO:
    python tools/verificar_cadena_resumen.py --max 15
SALIDA:
    data/demo/verificacion_cadena_resumen.json + tabla en consola
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))

import httpx  # noqa: E402

from radar import config  # noqa: E402
from radar.harvester import abstract_chain  # noqa: E402

DEMO = RAIZ / "data" / "demo"

# Fuentes aceptables por plataforma. OJS puede declarar el resumen en `citation_abstract`
# o en `DC.Description`: las dos son correctas. En Redalyc lo correcto es el campo VACÍO
# (fichas *stub* cuyo PDF tampoco trae resumen): cualquier texto ahí sería invención.
ESPERADO = {"scielo": {"citation_abstract", "dc_description"},
            "ojs": {"citation_abstract", "dc_description"},
            "redalyc": {"none"}}

# Por debajo de este tamaño la respuesta no es una ficha de artículo (CDN, error, muro).
MIN_BYTES_FICHA = 2000


def plataforma(url: str) -> str:
    for clave in ("redalyc", "scielo"):
        if clave in url:
            return clave
    return "ojs"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paginas", default="data/demo/paginas_prueba.txt")
    ap.add_argument("--max", type=int, default=15)
    args = ap.parse_args()

    lista = RAIZ / args.paginas
    urls = [l.strip() for l in lista.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")][: args.max]

    cliente = httpx.Client(headers={"User-Agent": config.USER_AGENT},
                           follow_redirects=True, timeout=60.0)
    dir_html = DEMO / "html"

    print("=" * 112)
    print(f"CADENA DETERMINISTA DEL RESUMEN — {len(urls)} páginas (sin modelo)")
    print("=" * 112)
    print(f"{'plataforma':10} {'página':30} {'fuente':18} {'chars':>6} {'PDF':>5} {'t':>6} esperado")

    informe, aciertos, fallos = [], 0, []
    for url in urls:
        destino = dir_html / (re.sub(r"\W+", "_", url)[-70:] + ".html")
        if destino.exists():
            html = destino.read_text(encoding="utf-8", errors="replace")
        else:
            try:
                r = cliente.get(url)
                html = r.text
                destino.write_text(html, encoding="utf-8")
            except Exception as e:
                print(f"{plataforma(url):10} {url[-28:]:30} fallo de red {type(e).__name__}")
                continue

        etiquetas = abstract_chain.metas(html)
        t0 = time.time()
        salida = abstract_chain.resolve_abstract(
            html, http=cliente,
            titulo=etiquetas.get("citation_title", ""),
            idioma=etiquetas.get("citation_language", ""),
        )
        segundos = time.time() - t0

        ficha_ok = len(html.encode("utf-8")) >= MIN_BYTES_FICHA
        esperadas = ESPERADO[plataforma(url)]
        coincide = salida["fuente"] in esperadas
        if ficha_ok:
            aciertos += coincide
        if ficha_ok and not coincide:
            fallos.append({"url": url, "obtenido": salida["fuente"], "esperado": sorted(esperadas),
                           "detalle": salida["detalle"]})

        informe.append({"url": url, "plataforma": plataforma(url), "ficha_descargada": ficha_ok,
                        "bytes": len(html.encode("utf-8")), "fuente": salida["fuente"],
                        "caracteres": salida["caracteres"], "pdf_url": salida["pdf_url"],
                        "detalle": salida["detalle"], "segundos": round(segundos, 2),
                        "esperado": sorted(esperadas), "coincide": coincide})
        marca = "" if coincide else ("  <-- REVISAR" if ficha_ok else "  (ficha no descargada)")
        print(f"{plataforma(url):10} {url[-28:]:30} {salida['fuente']:18} "
              f"{salida['caracteres']:>6} {'sí' if salida['pdf_url'] else '—':>5} "
              f"{segundos:>6.1f} {'/'.join(sorted(esperadas))}{marca}")

    cliente.close()

    por_fuente: dict[str, int] = {}
    for f in informe:
        por_fuente[f["fuente"]] = por_fuente.get(f["fuente"], 0) + 1
    con_ficha = [f for f in informe if f["ficha_descargada"]]

    print("-" * 112)
    print(f"Fuentes usadas: {por_fuente}")
    print(f"Fichas descargadas correctamente: {len(con_ficha)}/{len(informe)}")
    print(f"Coincidencia con el contraste esperado: {aciertos}/{len(con_ficha)}")
    if fallos:
        print("\nDiscrepancias:")
        for f in fallos:
            print(f"  {f['url'][-40:]:42} obtenido={f['obtenido']:18} "
                  f"esperado={'/'.join(f['esperado']):28} {f['detalle']}")
    sin_ficha = [f for f in informe if not f["ficha_descargada"]]
    if sin_ficha:
        print("\nFichas no descargadas (no es fallo de la cadena, es del recolector):")
        for f in sin_ficha:
            print(f"  {f['url'][-46:]:48} {f['bytes']} bytes")

    salida_json = {"n_paginas": len(informe), "coincidencias": aciertos,
                   "fuentes": por_fuente, "discrepancias": fallos, "paginas": informe}
    (DEMO / "verificacion_cadena_resumen.json").write_text(
        json.dumps(salida_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetalle: data/demo/verificacion_cadena_resumen.json")


if __name__ == "__main__":
    main()
