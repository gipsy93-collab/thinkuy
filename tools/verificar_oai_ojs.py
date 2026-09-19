"""Verificación en vivo del micro-cosechador OJS `/oai` sobre revistas reales.

Contraste: por la vía de hoy (una petición por artículo + PDF si falta el resumen) estos
mismos artículos costaron ~1 descarga cada uno. Por OAI-PMH, **una petición cubre N
artículos** y el resumen llega en `dc:description`.

USO:
    python tools/verificar_oai_ojs.py
SALIDA:
    data/demo/verificacion_oai_ojs.json + informe en consola
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))

import httpx  # noqa: E402

from radar import config  # noqa: E402
from radar.harvester import ojs_oai  # noqa: E402

REVISTAS = [
    "https://dspace.palermo.edu/ojs/index.php/cdc",
    "https://redipe.org/index.php/1",
]

MAX_REGISTROS = 25


def main() -> None:
    cliente = httpx.Client(headers={"User-Agent": config.USER_AGENT},
                           follow_redirects=True, timeout=60.0)
    informe = []

    for url in REVISTAS:
        print("=" * 104)
        print(f"REVISTA: {url}")
        print("=" * 104)

        t0 = time.time()
        endpoint, intentos = ojs_oai.detect_oai_endpoint(url, cliente)
        t_deteccion = time.time() - t0
        for intento in intentos:
            estado = "OK" if intento["ok"] else "no"
            print(f"  sonda {estado:3} {intento['endpoint']}"
                  + (f"  -> {intento.get('repositorio') or intento.get('detalle', '')}"[:70] if not intento["ok"] else
                     f"  -> repositorio: {intento.get('repositorio')}"))
        if not endpoint:
            print("  SIN ENDPOINT OAI\n")
            informe.append({"url": url, "endpoint": None, "intentos": intentos})
            continue

        t0 = time.time()
        articulos = ojs_oai.harvest_journal(cliente, endpoint, max_records=MAX_REGISTROS)
        t_cosecha = time.time() - t0
        perfil = ojs_oai.journal_profile(articulos)

        print(f"\n  endpoint activo: {endpoint}")
        print(f"  detección: {t_deteccion:.1f}s · cosecha de {len(articulos)} artículos: {t_cosecha:.1f}s "
              f"({t_cosecha / max(1, len(articulos)):.2f}s por artículo)")
        print(f"  años: {perfil.get('anio_min')}–{perfil.get('anio_max')} · idiomas: {perfil.get('idiomas')}")
        print(f"  cobertura: resumen {perfil['cobertura']['con_resumen_pct']}% · "
              f"DOI {perfil['cobertura']['con_doi_pct']}% · "
              f"resumen medio {perfil['resumen_chars_promedio']} chars")
        print(f"  palabras clave más frecuentes: {list(perfil['palabras_clave_frecuentes'])[:6]}")
        print("\n  primeros artículos:")
        for a in articulos[:4]:
            resumen = (a.abstract or "")
            print(f"    · {a.title[:72]}")
            print(f"      {a.year} · {a.lang} · doi={a.doi or '—'} · resumen={len(resumen)} chars"
                  + (f" · «{resumen[:90]}…»" if resumen else " · (sin resumen en el registro OAI)"))
        print()

        informe.append({"url": url, "endpoint": endpoint, "intentos": intentos,
                        "segundos_deteccion": round(t_deteccion, 2),
                        "segundos_cosecha": round(t_cosecha, 2),
                        "total": len(articulos), "perfil": perfil,
                        "articulos": [a.to_dict() for a in articulos]})

    cliente.close()
    (RAIZ / "data" / "demo" / "verificacion_oai_ojs.json").write_text(
        json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Detalle: data/demo/verificacion_oai_ojs.json")


if __name__ == "__main__":
    main()
