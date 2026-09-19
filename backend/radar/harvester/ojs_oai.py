"""Micro-cosechador OJS vía `/oai` (OAI-PMH + `oai_dc`).

Cubre la pieza pendiente del Modo Revista: al ingresar la URL de una revista OJS se
detecta su endpoint OAI-PMH y se cosecha su metadata (título, autores, resumen,
palabras clave, año) **sin descargar PDFs y sin usar ningún modelo**.

Por qué importa (medido el 18-09-2026): el resumen de OJS vive en `DC.Description`, que
es exactamente el vocabulario que publica `oai_dc`. Una sola petición `ListRecords`
entrega lo que hoy cuesta una descarga por artículo.

Uso:

    endpoint, intentos = detect_oai_endpoint("https://revista.edu/index.php/r", http)
    articulos = harvest_journal(http, endpoint, date_from="2023-01-01", max_records=200)
    perfil = journal_profile(articulos)
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from urllib.parse import urlparse, urlunparse

import httpx

from . import oai_dc
from .base import Article

log = logging.getLogger("radar.ojs_oai")

# Rutas habituales del endpoint OAI de OJS, en orden de probabilidad.
RUTAS_OAI = ["/index.php/{revista}/oai", "/oai", "/index.php/oai", "/oai/oai2"]


def _sin_barra(url: str) -> str:
    return url.rstrip("/")


def candidatos(url: str) -> list[str]:
    """Endpoints OAI candidatos para una URL de revista OJS, sin repetir."""
    base = _sin_barra(url.split("#")[0].split("?")[0])
    partes = urlparse(base)
    origen = urlunparse((partes.scheme, partes.netloc, "", "", "", ""))
    if not partes.scheme:
        origen = "https://" + partes.netloc if partes.netloc else ""

    salidas: list[str] = []
    # 1) /index.php/<revista>/oai — el patrón canónico de OJS 3.
    m = re.search(r"/index\.php/([^/]+)", partes.path or "")
    if m:
        salidas.append(f"{origen}/index.php/{m.group(1)}/oai")
    # 2) rutas relativas a la raíz del sitio.
    for ruta in RUTAS_OAI:
        if "{revista}" in ruta:
            continue
        salidas.append(origen + ruta)
    # 3) `oai` colgando de la propia URL.
    salidas.append(base + "/oai")

    vistas, unicas = set(), []
    for s in salidas:
        if s and s not in vistas:
            vistas.add(s)
            unicas.append(s)
    return unicas


def detect_oai_endpoint(url: str, http: httpx.Client) -> tuple[str | None, list[dict]]:
    """Prueba los candidatos con `Identify`. Devuelve (endpoint_activo, intentos).

    Si ningún candidato responde, se inspecciona la propia página de la revista buscando
    un enlace declarado al endpoint (algunas plantillas lo publican). Así se evita
    adivinar rutas cuando la instalación usa un prefijo no estándar.
    """
    intentos: list[dict] = []
    for candidato in candidatos(url):
        try:
            info = oai_dc.identify(http, candidato)
        except Exception as e:
            intentos.append({"endpoint": candidato, "ok": False, "detalle": f"{type(e).__name__}: {e}"[:120]})
            continue
        if info.get("repository_name"):
            intentos.append({"endpoint": candidato, "ok": True,
                             "repositorio": info["repository_name"]})
            return candidato, intentos
        intentos.append({"endpoint": candidato, "ok": False, "detalle": "sin repositoryName"})

    for candidato in _declarados_en_la_pagina(url, http):
        if any(i["endpoint"] == candidato for i in intentos):
            continue
        try:
            info = oai_dc.identify(http, candidato)
        except Exception as e:
            intentos.append({"endpoint": candidato, "ok": False, "origen": "página",
                             "detalle": f"{type(e).__name__}: {e}"[:120]})
            continue
        if info.get("repository_name"):
            intentos.append({"endpoint": candidato, "ok": True, "origen": "página",
                             "repositorio": info["repository_name"]})
            return candidato, intentos
        intentos.append({"endpoint": candidato, "ok": False, "origen": "página",
                         "detalle": "sin repositoryName"})
    return None, intentos


def _declarados_en_la_pagina(url: str, http: httpx.Client) -> list[str]:
    """URLs con `/oai` que la propia página de la revista declare (href o texto)."""
    partes = urlparse(url if "://" in url else "https://" + url)
    origen = urlunparse((partes.scheme, partes.netloc, "", "", "", ""))
    try:
        respuesta = http.get(url, timeout=45.0)
        if respuesta.status_code >= 400:
            return []
        html = respuesta.text
    except Exception:
        return []

    encontrados, vistos = [], set()
    for bruto in re.findall(r'(?:href|action)=["\']([^"\']*?/oai[^"\']*)["\']', html, re.I):
        absoluto = bruto if bruto.startswith("http") else origen + ("" if bruto.startswith("/") else "/") + bruto
        if absoluto not in vistos:
            vistos.add(absoluto)
            encontrados.append(absoluto)
    return encontrados


def harvest_journal(http: httpx.Client, endpoint: str, *, date_from: str | None = None,
                    until: str | None = None, set_spec: str | None = None,
                    metadata_prefix: str = "oai_dc", max_records: int = 200,
                    delay: float | None = None) -> list[Article]:
    """Cosecha una revista completa (o un set de ella). Los registros ilegibles se omiten."""
    articulos: list[Article] = []
    base_url = endpoint.rsplit("/oai", 1)[0]
    for registro in oai_dc.list_records(http, endpoint, metadata_prefix=metadata_prefix,
                                        set_spec=set_spec, date_from=date_from, until=until,
                                        max_records=max_records, delay=delay):
        try:
            articulo = oai_dc.article_from_record(registro, source="ojs", base_url=base_url)
        except Exception as e:
            log.warning("registro OJS ilegible: %s", e)
            continue
        if articulo:
            articulos.append(articulo)
    return articulos


def journal_profile(articulos: list[Article]) -> dict:
    """Huella editorial (*Editorial DNA*): qué publica la revista y con qué calidad de metadata.

    Todo se calcula sobre lo cosechado; no interpreta ni estima. Sirve de base para el
    análisis de brechas editoriales y la afinidad de evaluadores.
    """
    total = len(articulos)
    if not total:
        return {"total": 0, "detalle": "sin registros cosechados"}

    anios = [a.year for a in articulos if a.year]
    idiomas = Counter((a.lang or "").lower() for a in articulos if a.lang)
    revistas = Counter(a.journal_title for a in articulos if a.journal_title)
    palabras: Counter = Counter()
    for a in articulos:
        palabras.update(k.strip().lower() for k in (a.keywords or []) if k and k.strip())

    con_resumen = sum(1 for a in articulos if (a.abstract or "").strip())
    con_doi = sum(1 for a in articulos if a.doi)
    largos = [len((a.abstract or "").strip()) for a in articulos if (a.abstract or "").strip()]

    return {
        "total": total,
        "anio_min": min(anios) if anios else None,
        "anio_max": max(anios) if anios else None,
        "por_anio": dict(sorted(Counter(anios).items())),
        "idiomas": dict(idiomas.most_common()),
        "revistas": dict(revistas.most_common(5)),
        "palabras_clave_frecuentes": dict(palabras.most_common(20)),
        "cobertura": {
            "con_resumen": con_resumen,
            "con_resumen_pct": round(100 * con_resumen / total, 1),
            "con_doi": con_doi,
            "con_doi_pct": round(100 * con_doi / total, 1),
            "con_palabras_clave": sum(1 for a in articulos if a.keywords),
        },
        "resumen_chars_promedio": round(sum(largos) / len(largos)) if largos else 0,
    }


def harvest_from_url(url: str, http: httpx.Client, **kwargs) -> dict:
    """Cadena completa para el Modo Revista: detectar endpoint -> cosechar -> perfilar."""
    endpoint, intentos = detect_oai_endpoint(url, http)
    if not endpoint:
        return {"url": url, "endpoint": None, "intentos": intentos,
                "detalle": "no se encontró endpoint OAI-PMH", "articulos": [], "perfil": {}}
    articulos = harvest_journal(http, endpoint, **kwargs)
    return {"url": url, "endpoint": endpoint, "intentos": intentos,
            "repositorio": oai_dc.identify(http, endpoint).get("repository_name", ""),
            "total": len(articulos), "perfil": journal_profile(articulos),
            "articulos": [a.to_dict() for a in articulos]}
