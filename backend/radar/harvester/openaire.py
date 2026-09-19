"""Harvester OpenAIRE Graph v3 (api.openaire.eu/graph/v3/) — políticas y proyectos europeos.

Cubre literatura científica, reportes técnicos, entregables de políticas públicas
y proyectos de la Unión Europea (Horizonte Europa, FP7, H2020) con acceso abierto.
Gratuita, sin API key obligatoria.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ..normalize import unescape
from .base import Article

log = logging.getLogger("radar.openaire")

BASE_RESEARCH_PRODUCTS = "https://api.openaire.eu/graph/v3/research-products"
BASE_PROJECTS = "https://api.openaire.eu/graph/v3/projects"


def parse_item(item: dict[str, Any]) -> Article | None:
    """Convierte un producto de investigación de OpenAIRE Graph v3 a Article."""
    title = item.get("mainTitle") or ""
    if not title:
        other_titles = item.get("otherTitles") or []
        if other_titles and isinstance(other_titles, list):
            title = str(other_titles[0])
    title = unescape(title).strip()
    if not title:
        return None

    # DOI y PIDs
    doi: str | None = None
    for pid in item.get("pids") or []:
        scheme = str(pid.get("scheme") or "").strip().lower()
        val = str(pid.get("value") or "").strip()
        if scheme == "doi" and val:
            doi = val.lower().replace("https://doi.org/", "").replace("http://doi.org/", "")
            break

    # Autores
    authors: list[dict[str, Any]] = []
    for au in item.get("authors") or []:
        full_name = au.get("fullName") or ""
        given = au.get("name") or ""
        family = au.get("surname") or ""
        if not full_name and (given or family):
            full_name = f"{given} {family}".strip()
        full_name = unescape(full_name).strip()
        if not full_name:
            continue
        if not given and not family:
            if " " in full_name:
                given, family = full_name.rsplit(" ", 1)
            else:
                given, family = "", full_name

        orcid: str | None = None
        au_pid = au.get("pid")
        if isinstance(au_pid, dict):
            if str(au_pid.get("scheme") or "").lower() == "orcid":
                orcid = str(au_pid.get("value") or "").replace("https://orcid.org/", "").strip()
        elif isinstance(au_pid, str) and "orcid.org" in au_pid:
            orcid = au_pid.replace("https://orcid.org/", "").replace("http://orcid.org/", "").strip()

        authors.append({"given": given, "family": family, "orcid": orcid or None})

    # Fecha y Año
    pub_date = str(item.get("publicationDate") or "").strip() or None
    year: int | None = None
    if pub_date:
        y_match = re.search(r"\b(19\d\d|20\d\d)\b", pub_date)
        if y_match:
            try:
                year = int(y_match.group(1))
            except ValueError:
                year = None

    # Contenedor / Revista / Congreso
    container = item.get("container") or {}
    journal = unescape(container.get("name") or "").strip() or None
    issn = container.get("issnOnline") or container.get("issnPrinted") or container.get("issnLinking") or None
    vol = container.get("vol") or None
    iss = container.get("iss") or None
    sp = container.get("sp") or ""
    ep = container.get("ep") or ""
    pages = f"{sp}-{ep}" if (sp and ep) else (sp or None)

    # Resumen / Abstract
    descriptions = item.get("descriptions") or []
    abstract: str | None = None
    if descriptions and isinstance(descriptions, list):
        # Tomar la primera descripción no vacía y limpiar etiquetas jats/html
        raw_desc = str(descriptions[0])
        clean_desc = re.sub(r"<[^>]+>", " ", raw_desc)
        abstract = unescape(" ".join(clean_desc.split())).strip() or None

    # Palabras clave / Materias
    keywords: list[str] = []
    for s in item.get("subjects") or []:
        subj_obj = s.get("subject") if isinstance(s, dict) else None
        if isinstance(subj_obj, dict):
            val = str(subj_obj.get("value") or "").strip()
            if val and len(val) > 2:
                keywords.append(val)

    # Open Access y URLs
    oa_code = str((item.get("bestAccessRight") or {}).get("code") or "").upper()
    oa_color = str(item.get("openAccessColor") or "").lower()
    is_oa = oa_code in {"OPEN", "OPEN ACCESS"} or oa_color in {"gold", "green", "diamond", "hybrid"}
    access = "open" if is_oa else "closed"

    url: str | None = None
    pdf_url: str | None = None
    for inst in item.get("instances") or []:
        inst_urls = inst.get("urls") or []
        for u in inst_urls:
            u_str = str(u).strip()
            if not url and u_str:
                url = u_str
            if u_str.lower().endswith(".pdf") or "pdf" in u_str.lower():
                pdf_url = u_str
                break

    if not url and doi:
        url = f"https://doi.org/{doi}"

    source_id = str(item.get("id") or "") or None

    return Article(
        title=title,
        source="openaire",
        doi=doi,
        abstract=abstract,
        keywords=keywords[:8],
        authors=authors,
        journal_title=journal,
        issn=issn,
        volume=vol,
        issue=iss,
        pages=pages,
        year=year,
        pub_date=pub_date,
        lang=item.get("language") or None,
        url=url,
        source_id=source_id,
        access=access,
        pdf_url=pdf_url,
        oa_status=oa_color or ("open" if is_oa else None),
    )


def _compact_for_openaire(query: str) -> str:
    """OpenAIRE Graph v3 restringe a un máximo estricto de 4 operadores lógicos (AND / OR).
    Si la consulta contiene más de 4, extrae los descriptores núcleo para evitar HTTP 400.
    """
    ops = re.findall(r'\b(?:AND|OR|NOT)\b', query, flags=re.IGNORECASE)
    if len(ops) <= 4:
        return query

    # Si hay bloques separados por AND
    and_blocks = re.split(r'\bAND\b', query, flags=re.IGNORECASE)
    if len(and_blocks) >= 2:
        b1_terms = re.findall(r'"([^"]+)"', and_blocks[0])
        b2_terms = re.findall(r'"([^"]+)"', and_blocks[1])
        t1 = f'"{b1_terms[0]}"' if b1_terms else and_blocks[0].strip("() ")
        t2_candidates = [f'"{t}"' if " " in t else t for t in b2_terms[:2]] if b2_terms else ["governance", "policy"]
        t2 = " OR ".join(t2_candidates)
        return f'{t1} AND ({t2})'

    quoted = re.findall(r'"([^"]+)"', query)
    if quoted:
        return " OR ".join(f'"{q}"' for q in quoted[:3])
    return query[:120]


def search(client: httpx.Client | None = None, query: str = "", limit: int = 15,
           timeout: float = 12.0) -> list[Article]:
    """Busca en OpenAIRE Graph v3 por texto y devuelve lista de Article."""
    clean_q = _compact_for_openaire(query.strip())
    if not clean_q:
        return []

    params: dict[str, Any] = {
        "search": clean_q,
        "pageSize": min(max(limit, 1), 50),
    }
    headers = {
        "User-Agent": "Thinkuy-Scientific-Radar/5.28 (https://thinkuy.org; mailto:info@thinkuy.org)",
        "Accept": "application/json",
    }

    should_close = False
    if client is None:
        client = httpx.Client(timeout=timeout)
        should_close = True

    articles: list[Article] = []
    try:
        resp = client.get(BASE_RESEARCH_PRODUCTS, params=params, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results") or []
            for item in results:
                art = parse_item(item)
                if art:
                    articles.append(art)
        else:
            log.warning("OpenAIRE Graph v3 HTTP %d: %s", resp.status_code, resp.text[:120])
    except Exception as e:
        log.warning("Fallo al conectar con OpenAIRE Graph v3: %s", e)
    finally:
        if should_close:
            client.close()

    return articles
