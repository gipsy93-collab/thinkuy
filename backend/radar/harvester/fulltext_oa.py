"""Resolución y descarga del PDF de ACCESO ABIERTO de un DOI (escalera **medida**).

La sonda `tools/probe_fulltext_routes.py` (22-09-2026) midió, sobre una muestra aleatoria de 60
artículos iberoamericanos, una cobertura del **85%** con esta escalera —frente al ~42% de
Unpaywall solo—:

  1. **Unpaywall** `best_oa_location.url_for_pdf`.
  2. **DOI → página del editor → `citation_pdf_url`**. El detalle que lo cambió todo: el enlace
     viene con `&amp;` sin desescapar, y sin desescaparlo SciELO ignora `format=pdf` y devuelve
     la página HTML (de ahí el «no es posible acceder al texto completo» aparente).

Regla legal: solo se descarga cuando la fuente declara acceso abierto (Unpaywall `is_oa`, o una
plataforma de acceso abierto conocida como SciELO/Redalyc). Se consulta `robots.txt` de las
páginas antes de bajarlas, y se valida que el cuerpo sea realmente un PDF (`%PDF`).
"""
from __future__ import annotations

import logging
import re
from html import unescape

import httpx

from .. import config
from . import render_js, unpaywall

log = logging.getLogger("radar.fulltext_oa")

# UA de navegador: los repositorios de acceso abierto suelen atender mejor a un navegador que a
# un bot. Se usa solo para leer fichas y PDFs ya declarados abiertos.
NAVEGADOR_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Prefijos DOI de plataformas de acceso abierto (diamante/abierto) conocidas y verificadas.
PREFIJOS_OA = ("10.1590/",)  # SciELO
HOSTS_OA = ("scielo.br", "scielo.org", "scielosp.org", "redalyc.org")

_WAF_RE = re.compile(
    r"(establishing a secure connection|checking your browser|cf-browser|attention required|just a moment)",
    re.IGNORECASE,
)
_NO_TEXT_RE = re.compile(
    r"(no es posible acceder|no se puede acceder|n[aã]o [eé] poss[ií]vel (acessar|acceder)|"
    r"texto completo n[aã]o dispon|full text is not available|texto completo.{0,20}remov)",
    re.IGNORECASE,
)


def _meta_citation_pdf(html: str) -> str | None:
    """Extrae `citation_pdf_url` de una ficha, **desescapando** entidades HTML."""
    m = re.search(
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r'<meta[^>]+content=["\']([^"\']+\.pdf[^"\']*)["\'][^>]+name=["\']citation_pdf_url["\']',
            html, re.IGNORECASE,
        )
    return unescape(m.group(1).strip()) if m else None


def _primer_enlace_pdf(html: str) -> str | None:
    for m in re.finditer(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html, re.IGNORECASE):
        href = unescape(m.group(1))
        if any(k in href.lower() for k in ("pdf", "/download", "descarga")):
            return href
    return None


def _es_plataforma_oa(doi: str, url_final: str = "") -> bool:
    if any(doi.startswith(p) for p in PREFIJOS_OA):
        return True
    host = (httpx.URL(url_final).host if url_final else "") or ""
    return any(h in host for h in HOSTS_OA)


def _candidatos(client: httpx.Client, doi: str, email: str) -> tuple[list[dict], str | None]:
    """URLs candidatas de PDF abierto, **en orden**, y el motivo si no hay ninguna."""
    doi = (doi or "").strip().lower()
    if not doi:
        return [], "doi_vacio"

    info = unpaywall.enrich_doi(client, doi, email=email) or {}
    candidatos: list[dict] = []

    # 1. Unpaywall
    if info.get("is_oa") and info.get("pdf_url"):
        candidatos.append({"pdf_url": info["pdf_url"], "ruta": "unpaywall", "is_oa": True,
                           "oa_status": info.get("oa_status"), "host_type": info.get("host_type")})

    # 2. DOI -> citation_pdf_url (solo si la fuente es de acceso abierto)
    motivo = "sin_acceso_abierto"
    if info.get("is_oa") or _es_plataforma_oa(doi):
        doi_url = f"https://doi.org/{doi}"
        if render_js.robots_permite(doi_url, http=client) is False:
            motivo = "robots_disallow"
        else:
            try:
                resp = client.get(doi_url, headers={"User-Agent": NAVEGADOR_UA}, timeout=45.0,
                                  follow_redirects=True)
            except Exception as e:
                resp = None
                motivo = f"error:{type(e).__name__}"
            if resp is not None:
                if resp.status_code != 200:
                    motivo = f"http_{resp.status_code}"
                elif _WAF_RE.search(resp.text):
                    motivo = "waf"
                else:
                    pdf = _meta_citation_pdf(resp.text) or _primer_enlace_pdf(resp.text)
                    if pdf:
                        if pdf.startswith("/"):
                            u = httpx.URL(str(resp.url))
                            pdf = f"{u.scheme}://{u.host}{pdf}"
                        candidatos.append({"pdf_url": pdf, "ruta": "doi_citation_pdf", "is_oa": True,
                                           "oa_status": info.get("oa_status"), "host_type": "publisher"})
                    else:
                        motivo = "declarado_sin_texto" if _NO_TEXT_RE.search(resp.text) else "sin_citation_pdf"

    return candidatos, (None if candidatos else motivo)


def resolve_pdf(client: httpx.Client, doi: str, *, email: str | None = None,
                validar: bool = True) -> dict:
    """Resuelve el PDF abierto de un DOI por la escalera medida.

    Con `validar=True` (por defecto) **descarga cada candidato y se queda con el primero cuyo
    cuerpo sea un PDF real**: Unpaywall puede devolver una URL que sirve HTML, y sin esta
    validación no habría fallback. Devuelve `body` con los bytes.

    Sin candidatos, `body=None` y `motivo` declarado (`sin_acceso_abierto`, `waf`,
    `declarado_sin_texto`, `descarga_fallida`…).
    """
    candidatos, motivo = _candidatos(client, doi, email or config.MAILTO)
    if not candidatos:
        return {"pdf_url": None, "ruta": None, "body": None, "motivo": motivo}
    if not validar:
        return {**candidatos[0], "body": None}
    for c in candidatos:
        body = download_pdf(client, c["pdf_url"])
        if body:
            return {**c, "body": body}
    return {**candidatos[0], "body": None, "motivo": "descarga_fallida"}


def download_pdf(client: httpx.Client, url: str) -> bytes | None:
    """Descarga una URL y devuelve los bytes **solo si el cuerpo es un PDF** (`%PDF`)."""
    if not url:
        return None
    if render_js.robots_permite(url, http=client) is False:
        return None
    try:
        resp = client.get(url, headers={"User-Agent": NAVEGADOR_UA}, timeout=60.0, follow_redirects=True)
    except Exception as e:
        log.warning("descarga PDF %s: %s", url, e)
        return None
    if resp.status_code >= 400:
        return None
    if resp.content[:4] != b"%PDF":
        log.info("El cuerpo de %s no es un PDF (content-type=%s)", url, resp.headers.get("content-type"))
        return None
    return resp.content
