"""Utilidades, clientes compartidos y funciones auxiliares para los routers de la API."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Request

from .. import config, db, profile, topics
from ..conversation import build_profile, fallback_profile, why_labels

log = logging.getLogger("radar.api")

_http = httpx.Client(
    headers={"User-Agent": config.USER_AGENT},
    follow_redirects=True,
    timeout=45.0,
)

_harvest_lock = False  # guard simple contra corridas concurrentes


def _extract_owner_id(request: Request, explicit_owner: str | None = None) -> str:
    """Extrae el identificador de usuario para aislamiento multiusuario.

    Prioridad:
    1. Parámetro explícito del payload o query.
    2. Cabecera HTTP `Authorization: Bearer <token>` verificada criptográficamente.
    3. Cabecera HTTP `X-User-Id`.
    4. Query parameter `owner_id`.
    5. Valor predeterminado 'default' (compatibilidad mono-usuario).
    """
    if explicit_owner and str(explicit_owner).strip():
        return str(explicit_owner).strip()
    from . import auth
    u = auth.extract_user_from_request(request)
    return u.get("user_id", "default")


def _safe_doi(doi: str) -> str:
    return doi.strip().lower()


def _field_profile(conn) -> dict:
    arts = db.load_anchor_articles(conn)
    return build_profile(arts) if arts else fallback_profile()


def _as_int(value, default: int, minimum: int, maximum: int) -> int:
    """Convierte un parámetro a entero dentro de un rango seguro."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _as_list(value) -> list[str] | None:
    """Normaliza una lista del query/body a una lista limpia de cadenas."""
    if value is None:
        return None
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        return None
    return items or None


def _widget_card(a: dict, lang: str) -> dict:
    conv = a.get("conversation") or {}
    aus = (a.get("authors") or [])
    names = []
    for au in aus:
        if isinstance(au, dict):
            names.append(f"{au.get('family') or ''} {au.get('given') or ''}".strip())
        elif au:
            names.append(str(au))
    names = [n for n in names if n]
    return {
        "title": a.get("title"),
        "url": a.get("url") or (f"https://doi.org/{a['doi']}" if a.get("doi") else None),
        "doi": a.get("doi"),
        "authors": names[:3],
        "journal_title": a.get("journal_title"),
        "year": a.get("year"),
        "pub_date": (a.get("pub_date") or "")[:10],
        "why": why_labels(conv, lang),
        "cites_anchor": bool(conv.get("cites_anchor")),
        "cfp_score": conv.get("cfp_score") or 0,
        "access": a.get("access"),
    }


def _query_articles(conn, days: int | None, langs: list[str], sources: list[str],
                    order: str = "pub_date", max_rows: int | None = None,
                    journal: str | None = None, keywords: list[str] | None = None) -> list:
    sql = "SELECT * FROM articles WHERE 1=1"
    params: list = []
    if journal:
        sql += " AND LOWER(journal_title) LIKE ?"
        j_pat = f"%{journal.lower().strip()}%"
        params.append(j_pat)
    if days:
        since = (date.today() - timedelta(days=days)).isoformat()
        sql += " AND pub_date >= ?"
        params.append(since)
    if langs:
        sql += f" AND (lang IN ({','.join('?' * len(langs))}) OR lang IS NULL)"
        params.extend(langs)
    if sources:
        sql += f" AND source IN ({','.join('?' * len(sources))})"
        params.extend(sources)
    if keywords:
        kw_parts = []
        like_pats = []
        for kw in keywords:
            pat = f"%{kw.lower()}%"
            like_pats.extend([pat] * 3)
            kw_parts.append(f"LOWER(title) LIKE ? OR LOWER(keywords) LIKE ? OR LOWER(abstract) LIKE ?")
        sql += f" AND ({' OR '.join(kw_parts)})"
        params.extend(like_pats)
    sql += " ORDER BY " + ("cited_by DESC, pub_date DESC" if order == "cited" else "pub_date DESC")
    if max_rows:
        sql += f" LIMIT {int(max_rows)}"
    rows = conn.execute(sql, params).fetchall()
    return [db._row_to_article(r) for r in rows]


def _with_display_keywords(articles: list, candidate_terms: list[str] | None = None, limit: int = 6) -> list:
    """Añade palabras clave utilizables sin alterar los metadatos declarados originales."""
    for article in articles:
        display_keywords, keyword_source = topics.display_keywords(article, candidate_terms=candidate_terms, limit=limit)
        article["display_keywords"] = display_keywords
        article["keyword_source"] = keyword_source
    return articles


def _date_int(pub_date: str | None) -> int:
    """Clave numérica de fecha ISO (YYYY-MM-DD) para ordenar; sin fecha = 0."""
    if not pub_date:
        return 0
    d = str(pub_date).replace("-", "")
    return int(d) if d.isdigit() else 0
