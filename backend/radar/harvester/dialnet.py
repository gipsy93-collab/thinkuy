"""Harvester Dialnet Dismax (dialnet.unirioja.es) — literatura científica hispánica e iberoamericana.

Extrae publicaciones, tesis, actas de congresos y monografías en español/portugués
mediante el motor de búsqueda documental Dismax público de la Fundación Dialnet.
"""
from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any
import httpx

from .base import Article

log = logging.getLogger("radar.dialnet")

BASE_SEARCH_URL = "https://dialnet.unirioja.es/buscar/documentos"
BASE_DIALNET = "https://dialnet.unirioja.es"


def parse_html(html: str) -> list[Article]:
    """Parsea el HTML devuelto por la búsqueda documental de Dialnet."""
    if not html:
        return []

    pattern = re.compile(
        r'<li\s+id=\"articulo(\d+)\"\s+class=\"articulo[^\"]*\">([\s\S]*?)</li>',
        re.IGNORECASE,
    )
    matches = pattern.findall(html)
    articles: list[Article] = []

    for code, block in matches:
        # Título y enlace
        t_match = re.search(r'<p\s+class=\"titulo\">[\s\S]*?<a\s+href=\"([^\"]*)\">([^<]+)</a>', block)
        if not t_match:
            continue
        rel_url = t_match.group(1).strip()
        raw_title = t_match.group(2).strip()
        title = unescape(raw_title).strip()
        if not title:
            continue

        full_url = f"{BASE_DIALNET}{rel_url}" if rel_url.startswith("/") else rel_url

        # Autores
        raw_authors = re.findall(r'<a\s+href=\"/servlet/autor\?codigo=\d+\">([^<]+)</a>', block)
        authors: list[dict[str, Any]] = []
        for a_str in raw_authors:
            clean_name = unescape(a_str).strip()
            if not clean_name:
                continue
            if " " in clean_name:
                given, family = clean_name.rsplit(" ", 1)
            else:
                given, family = "", clean_name
            authors.append({"given": given, "family": family, "orcid": None})

        # Localización / Revista / Congreso / Libro
        loc_match = re.search(r'<p\s+class=\"localizacion\">([\s\S]*?)</p>', block)
        loc_clean = ""
        journal: str | None = None
        issn: str | None = None
        if loc_match:
            loc_text = re.sub(r"<[^>]+>", " ", loc_match.group(1))
            loc_clean = unescape(" ".join(loc_text.split()))

            # Extraer ISSN si aparece
            issn_match = re.search(r"ISSN\s+([0-9]{4}-[0-9]{3}[0-9xX])", loc_clean, re.IGNORECASE)
            if issn_match:
                issn = issn_match.group(1).upper()

            # Nombre de la revista antes del primer separador o coma
            journal_match = re.search(r'<span class="titulo"><a[^>]*>([^<]+)</a>', loc_match.group(1))
            if journal_match:
                journal = unescape(journal_match.group(1)).strip()
            elif loc_clean:
                journal = loc_clean.split(",")[0].strip() or None

        # Año de publicación
        years = re.findall(r"\b(19\d\d|20\d\d)\b", loc_clean)
        year = int(years[-1]) if years else None

        # Acceso y Texto completo
        has_fulltext = "texto completo" in block.lower() or "/descarga/" in block.lower()
        access = "open" if has_fulltext else "unknown"

        pdf_url: str | None = None
        pdf_match = re.search(r'href=\"(/servlet/articulo\?codigo=\d+&amp;orden=\d+&amp;info=link_completo)\"', block)
        if pdf_match:
            pdf_url = f"{BASE_DIALNET}{unescape(pdf_match.group(1))}"

        articles.append(
            Article(
                title=title,
                source="dialnet",
                doi=None,
                authors=authors,
                journal_title=journal,
                issn=issn,
                year=year,
                lang="spa",
                url=full_url,
                source_id=f"dialnet:{code}",
                access=access,
                pdf_url=pdf_url,
                oa_status="open" if has_fulltext else None,
            )
        )

    return articles


def extract_article_details_from_html(html: str) -> dict[str, Any]:
    """Extrae abstract, DOI y metadatos complementarios de la ficha individual de un artículo de Dialnet."""
    if not html:
        return {}
    details: dict[str, Any] = {}

    # 1. Abstract
    m = re.search(r'<ul\s+id=[\'"]resumen[\'"][^>]*>([\s\S]*?)</ul>', html, re.IGNORECASE)
    if not m:
        m = re.search(r'<div[^>]*id=[\'"]resumen[\'"][^>]*>([\s\S]*?)</div>', html, re.IGNORECASE)
    if not m:
        m = re.search(r'<div[^>]*class=[\'"][^\'"]*resumen[^\'"]*[\'"][^>]*>([\s\S]*?)</div>', html, re.IGNORECASE)
    if not m:
        m = re.search(r'<section[^>]*class=[\'"][^\'"]*resumen[^\'"]*[\'"][^>]*>([\s\S]*?)</section>', html, re.IGNORECASE)

    if m:
        txt = unescape(re.sub(r'<[^>]+>', ' ', m.group(1)))
        txt = ' '.join(txt.split())
        # Limpiar prefijo de idioma que Dialnet a veces incluye
        txt = re.sub(r'^(?:español|portugu[eê]s|english|catal[aà]|galego|euskara)\s+', '', txt, flags=re.IGNORECASE)
        if len(txt) > 20:
            details['abstract'] = txt.strip()

    # 2. DOI
    doi_m = re.search(r'https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s"\'<>]+)', html, re.IGNORECASE)
    if not doi_m:
        doi_m = re.search(r'DOI:\s*(10\.\d{4,9}/[^\s"\'<>]+)', html, re.IGNORECASE)
    if doi_m:
        doi_val = doi_m.group(1).rstrip('.,;"\'<>').strip().lower()
        if doi_val.startswith('10.'):
            details['doi'] = doi_val

    return details


def fetch_article_details(url: str, client: httpx.Client | None = None, timeout: float = 6.0) -> dict[str, Any]:
    """Descarga la página del artículo en Dialnet y extrae detalles enriquecidos (abstract, DOI)."""
    if not url:
        return {}
    should_close = False
    if client is None:
        client = httpx.Client(timeout=timeout)
        should_close = True
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        }
        resp = client.get(url, headers=headers, follow_redirects=True)
        if resp.status_code == 200:
            return extract_article_details_from_html(resp.text)
    except Exception as e:
        log.debug("No se pudo obtener detalles de artículo Dialnet %s: %s", url, e)
    finally:
        if should_close:
            client.close()
    return {}


def search(client: httpx.Client | None = None, query: str = "", limit: int = 15,
           timeout: float = 12.0, hydrate: bool = True) -> list[Article]:
    """Busca en el motor documental Dismax de Dialnet y devuelve lista de Article hidratada."""
    clean_q = query.strip()
    if not clean_q:
        return []

    params = {
        "querysDismax.DOCUMENTAL_TODO": clean_q,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }

    should_close = False
    if client is None:
        client = httpx.Client(timeout=timeout)
        should_close = True

    articles: list[Article] = []
    try:
        resp = client.get(BASE_SEARCH_URL, params=params, headers=headers, follow_redirects=True)
        if resp.status_code == 200:
            parsed = parse_html(resp.text)
            articles = parsed[:limit]
            if hydrate and articles:
                import time
                for a in articles:
                    if a.url:
                        # Retraso para no disparar el anti-bot "Uuuups!" de Dialnet
                        time.sleep(1.2)
                        det = fetch_article_details(a.url, client=client, timeout=min(timeout, 6.0))
                        if det.get("abstract"):
                            a.abstract = det["abstract"]
                        if det.get("doi") and not a.doi:
                            a.doi = det["doi"]
        else:
            log.warning("Dialnet Dismax HTTP %d: %s", resp.status_code, resp.text[:120])
    except Exception as e:
        log.warning("Fallo al conectar con Dialnet: %s", e)
    finally:
        if should_close:
            client.close()

    return articles
