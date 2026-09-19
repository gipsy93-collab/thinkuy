"""AUDITORÍA DE FIDELIDAD EXTRACTIVA (métrica central del producto).

Para cada (página, modelo) con un campo devuelto, mide qué fracción del texto
devuelto aparece VERBATIM en el texto visible de la página. Un producto de
revisión sistemática exige spans literales: `PARCIAL` o `INVENTADO` no sirven.

Método (evita el falso negativo de comparar contra el HTML con etiquetas):
  * `texto_pagina` = HTML sin etiquetas, entidades resueltas, acentos y espacios normalizados.
  * `cob` = fracción de ventanas de 6 palabras del texto devuelto presentes en `texto_pagina`.
  * VERBATIM si cob >= 0.80 · PARCIAL si cob >= 0.40 · INVENTADO si cob < 0.40.

Además marca páginas *stub* (el fetcher no trajo el artículo, p. ej. Redalyc sirve
el resumen en un iframe): en ellas la comparación de resúmenes NO es válida.

USO:
    python tools/auditar_fidelidad.py                 # las 15 páginas del lote
SALIDA:
    data/demo/auditoria_fidelidad.json + tabla en consola
"""
from __future__ import annotations

import html as H
import json
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

DEMO = RAIZ / "data" / "demo"
MODELOS = ("sch3b", "sch8b", "qwen7b")
VENTANA = 6
UMBRAL_VERBATIM = 0.80
UMBRAL_PARCIAL = 0.40


def norm(t: object) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(t or "")) if not unicodedata.combining(c))
    s = s.replace("\u00ad", "")
    return re.sub(r"\s+", " ", s).strip().lower()


def texto_visible(raw: str) -> str:
    """HTML -> texto: etiquetas fuera (como espacio), scripts/estilos fuera, entidades resueltas."""
    limpio = re.sub(r"<(script|style|noscript)\b[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
    limpio = re.sub(r"<[^>]+>", " ", limpio)
    return norm(H.unescape(limpio))


def cache_de(url: str) -> Path:
    return DEMO / "html" / (re.sub(r"\W+", "_", url)[-70:] + ".html")


def cobertura_verbatim(devuelto: str, pagina: str) -> float:
    """Fracción de ventanas de VENTANA palabras del texto devuelto que están en la página."""
    palabras = norm(devuelto).split()
    if len(palabras) < VENTANA:
        return 1.0 if norm(devuelto) and norm(devuelto) in pagina else 0.0
    inicios = range(0, len(palabras) - VENTANA + 1, 2)
    total = presentes = 0
    for i in inicios:
        total += 1
        if " ".join(palabras[i:i + VENTANA]) in pagina:
            presentes += 1
    return round(round(presentes / total, 2), 2) if total else 0.0


def clasificar(cob: float) -> str:
    if cob >= UMBRAL_VERBATIM:
        return "VERBATIM"
    if cob >= UMBRAL_PARCIAL:
        return "PARCIAL"
    return "INVENTADO"


def main() -> None:
    detalle: dict[str, dict] = {}
    for nombre in MODELOS:
        d = json.loads((DEMO / f"comparacion_lote_{nombre}.json").read_text(encoding="utf-8"))
        for f in d["detalle"]:
            detalle.setdefault(f["url"], {})[nombre] = f.get(nombre) or {}

    informe = []
    print("=" * 104)
    print("FIDELIDAD EXTRACTIVA DEL CAMPO `resumen` — ¿el texto está literal en la página?")
    print(f"(ventanas de {VENTANA} palabras · VERBATIM >= {UMBRAL_VERBATIM} · PARCIAL >= {UMBRAL_PARCIAL})")
    print("=" * 104)
    print(f"{'página':30} {'KB':>6} {'stub':>5} " + " ".join(f"{m:>16}" for m in MODELOS))
    print("-" * 104)

    for url, vias in detalle.items():
        ruta = cache_de(url)
        if not ruta.exists():
            print(f"{url[-28:]:30} {'—':>6} {'—':>5} (sin caché)")
            continue
        raw = ruta.read_text(encoding="utf-8", errors="replace")
        kb = len(raw.encode("utf-8")) / 1024
        pagina = texto_visible(raw)
        hay_abstract = norm("resumo") in pagina or norm("abstract") in pagina or norm("resumen") in pagina
        stub = kb < 20 or not hay_abstract
        fila = {"url": url, "kb": round(kb, 1), "stub": stub, "campos": {}}
        celdas = []
        for m in MODELOS:
            texto = norm((vias.get(m) or {}).get("resumen") or "")
            if not texto:
                celdas.append("—")
                fila["campos"][m] = {"estado": "vacio", "cobertura": 0.0, "chars": 0}
                continue
            cob = cobertura_verbatim(texto, pagina)
            estado = clasificar(cob)
            fila["campos"][m] = {"estado": estado, "cobertura": round(cob, 2), "chars": len(texto)}
            celdas.append(f"{estado} {cob:.2f}")
        informe.append(fila)
        print(f"{url[-28:]:30} {kb:6.1f} {str(stub):>5} " + " ".join(f"{c:>16}" for c in celdas))

    print("-" * 104)
    print(f"{'modelo':10} {'VERBATIM':>9} {'PARCIAL':>8} {'INVENTADO':>10} {'vacío':>7} {'invalidado por stub':>21} {'cobertura media':>16}")
    for m in MODELOS:
        c = {"VERBATIM": 0, "PARCIAL": 0, "INVENTADO": 0, "vacio": 0}
        cobs, invalidados = [], 0
        for fila in informe:
            d = fila["campos"].get(m) or {"estado": "vacio", "cobertura": 0.0}
            c[d["estado"]] += 1
            if d["estado"] != "vacio":
                cobs.append(d["cobertura"])
            if fila["stub"]:
                invalidados += 1
        media = round(sum(cobs) / len(cobs), 3) if cobs else None
        print(f"{m:10} {c['VERBATIM']:>9} {c['PARCIAL']:>8} {c['INVENTADO']:>10} {c['vacio']:>7} {invalidados:>21} {str(media):>16}")

    salida = {"ventana_palabras": VENTANA, "umbral_verbatim": UMBRAL_VERBATIM,
              "umbral_parcial": UMBRAL_PARCIAL, "paginas": informe}
    (DEMO / "auditoria_fidelidad.json").write_text(json.dumps(salida, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")
    print(f"\nDetalle: data/demo/auditoria_fidelidad.json")


if __name__ == "__main__":
    main()
