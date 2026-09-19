# -*- coding: utf-8 -*-
"""Resolución de dominio, metadatos y portales multi-revista de publicaciones científicas."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .. import config, db
from ..normalize import norm, edit_distance, unescape
from .common import (
    log,
    KNOWN_JOURNAL_DOMAINS,
    _clean_domain,
    _split_url_scope,
    _url_matches_scope,
    _is_portal_host,
    _get_db_conn,
)

def _resolve_journal_domain_openalex(query: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Consulta OpenAlex Sources API para resolver el dominio oficial, ISSN y metadatos
    de cualquier revista del mundo que no esté en el catálogo local.
    """
    clean_q = query.strip()
    if not clean_q or len(clean_q) < 3:
        return None, {}

    url = f"https://api.openalex.org/sources?search={urllib.parse.quote(clean_q)}&per-page=5"
    req = urllib.request.Request(
        url,
        headers=config.openalex_headers("Thinkuy-Radar/1.0 (mailto:info@thinkuy.org; https://thinkuy.org)")
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read().decode("utf-8"))
            results = data.get("results") or []
            if not results:
                return None, {}

            chosen = None
            for item in results:
                if item.get("type") == "journal" and item.get("homepage_url"):
                    chosen = item
                    break
            if not chosen:
                for item in results:
                    if item.get("homepage_url"):
                        chosen = item
                        break
            if not chosen:
                chosen = results[0]

            home = chosen.get("homepage_url") or ""
            domain = None
            if home:
                parsed = urllib.parse.urlparse(home)
                domain = parsed.netloc or None
                if domain and domain.startswith("www."):
                    domain = domain[4:]

            issn_val = chosen.get("issn_l") or (chosen.get("issn") or ["N/D"])[0] or "N/D"
            title = chosen.get("display_name") or clean_q
            host_org = chosen.get("host_organization_name") or "N/D"
            country = chosen.get("country_code") or "N/D"

            concepts = chosen.get("x_concepts") or []
            category = concepts[0].get("display_name") if concepts else "Investigación Científica"
            summary_stats = chosen.get("summary_stats") or {}

            return domain, {
                "journal_title": title,
                "domain": domain or "N/D",
                "issn": issn_val,
                "category": category,
                "country": country,
                "publisher": host_org,
                "global_works": chosen.get("works_count", 0),
                "global_cites": chosen.get("cited_by_count", 0),
                "h_index": summary_stats.get("h_index", "N/D"),
                "is_oa": chosen.get("is_oa", False),
                "source": "OpenAlex Global Registry",
            }
    except Exception as e:
        log.warning("Fallo al resolver revista en OpenAlex Sources: %s", e)
        return None, {}


def _detect_shared_host(conn: sqlite3.Connection, domain: str) -> bool:
    """True si el dominio aloja más de una revista distinta en el catálogo (portal OJS compartido).

    En ese caso la Centralidad Armónica/PageRank corresponden al PORTAL completo, no a la
    revista concreta — la métrica del Web Graph opera a nivel de dominio y no puede distinguirlas."""
    if not domain or domain == "N/D":
        return False
    curated: Dict[str, set] = {}
    for key, dom in KNOWN_JOURNAL_DOMAINS.items():
        curated.setdefault(dom, set()).add(key)
    if domain in curated and len(curated[domain]) > 1:
        return True
    try:
        row = conn.execute(
            """SELECT COUNT(DISTINCT journal_title) n FROM (
                   SELECT journal_title FROM articles
                   WHERE url LIKE ? AND journal_title IS NOT NULL AND TRIM(journal_title) != ''
                   LIMIT 8000)""",
            (f"%{domain}%",),
        ).fetchone()
        return bool(row and row[0] and row[0] > 1)
    except Exception:
        return False


def _probe_url_for_journal_meta(
    url_or_domain: str,
    domain: str,
    segment: Optional[str],
    db_path: str = config.DB_PATH,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Intenta extraer el título e ISSN reales de una revista a partir de su URL o dominio:
    1. Busca en artículos locales que coincidan con el dominio o segmento.
    2. Si es URL accesible, sondea levemente la cabecera/HTML para extraer ISSNs reales.
    3. Coteja los ISSNs hallados con la base de datos local Latindex (journals).
    """
    conn = _get_db_conn(db_path)
    try:
        # 1. Artículos locales coincidentes
        art_match = conn.execute(
            """SELECT journal_title, issn FROM articles
               WHERE (url LIKE ? OR url LIKE ?) AND journal_title IS NOT NULL
               LIMIT 1""",
            (f"%{domain}%", f"%/{segment}%" if segment else f"%{domain}%"),
        ).fetchone()
        if art_match and art_match["journal_title"]:
            return art_match["journal_title"], art_match["issn"] or None, None

        # 2. Si el input parece URL completa o dominio navegable, sondear HTML para ISSNs
        probe_url = url_or_domain if url_or_domain.startswith("http") else f"https://{url_or_domain}"
        issns_found: set[str] = set()
        page_title: Optional[str] = None
        html_snippet = ""
        try:
            req = urllib.request.Request(
                probe_url,
                headers={"User-Agent": "Thinkuy-Bot/1.0 (mailto:info@thinkuy.org; Mozilla/5.0)"}
            )
            with urllib.request.urlopen(req, timeout=4.0) as r:
                html_snippet = r.read(180000).decode("utf-8", errors="ignore")
                for m in re.findall(r"\b\d{4}-\d{3}[\dX]\b", html_snippet):
                    issns_found.add(m)
                tm = re.search(r"<title>(.*?)</title>", html_snippet, re.IGNORECASE)
                if tm:
                    raw_t = tm.group(1).strip()
                    parts = [p.strip() for p in re.split(r"[|\-–—]", raw_t) if len(p.strip()) > 3]
                    if parts:
                        page_title = parts[0]
        except Exception:
            pass

        # 2b. Si no encontramos ISSNs directamente en portada, explorar enlaces de revistas del portal
        if not issns_found and html_snippet:
            sub_links = re.findall(r'href=[\'"]([^\'"]*(?:revista|journal|publicacion|index\.php)[^\'"]*)[\'"]', html_snippet, re.IGNORECASE)
            for sub in sub_links[:3]:
                sub_url = urllib.parse.urljoin(probe_url, sub)
                try:
                    s_req = urllib.request.Request(
                        sub_url,
                        headers={"User-Agent": "Thinkuy-Bot/1.0 (mailto:info@thinkuy.org; Mozilla/5.0)"}
                    )
                    with urllib.request.urlopen(s_req, timeout=3.0) as s_res:
                        s_html = s_res.read(150000).decode("utf-8", errors="ignore")
                        for m in re.findall(r"\b\d{4}-\d{3}[\dX]\b", s_html):
                            issns_found.add(m)
                    if issns_found:
                        break
                except Exception:
                    pass

        # 3. Cruzar ISSNs hallados con tabla journals (Latindex / Catálogo)
        for issn in issns_found:
            j_row = conn.execute(
                """SELECT title, issn_online, issn_print, country, subject_areas 
                   FROM journals 
                   WHERE LOWER(issn_online) = ? OR LOWER(issn_print) = ? LIMIT 1""",
                (issn.lower(), issn.lower()),
            ).fetchone()
            if j_row:
                return j_row["title"], (j_row["issn_online"] or j_row["issn_print"] or issn), j_row["country"]

        # 4. Si tenemos ISSNs y no están en catálogo local, resolverlos en OpenAlex
        if issns_found:
            def _is_year_range(s: str) -> bool:
                p1, _, p2 = s.partition("-")
                return p1.isdigit() and p2.isdigit() and 1990 <= int(p1) <= 2030 and 1990 <= int(p2) <= 2030

            valid_issns = [i for i in issns_found if not _is_year_range(i)]
            candidate_issns = valid_issns or list(issns_found)

            # Consultar OpenAlex para encontrar la revista insignia o con más obras
            best_source = None
            best_issn = None
            for cand in candidate_issns[:3]:
                try:
                    oa_url = f"https://api.openalex.org/sources?filter=issn:{cand}&mailto=info@thinkuy.org"
                    oa_req = urllib.request.Request(oa_url, headers=config.openalex_headers("Thinkuy-EditorialRadar/1.0"))
                    with urllib.request.urlopen(oa_req, timeout=3.5) as oa_res:
                        data = json.loads(oa_res.read().decode("utf-8"))
                        results = data.get("results") or []
                        if results:
                            src = results[0]
                            w_count = src.get("works_count", 0)
                            if not best_source or w_count > best_source.get("works_count", 0):
                                best_source = src
                                best_issn = cand
                except Exception:
                    pass

            if best_source:
                country_code = best_source.get("country_code")
                return best_source.get("display_name") or page_title, best_issn, country_code

            chosen_issn = candidate_issns[0]
            return page_title, chosen_issn, None

        # 5. Si no hay ISSNs, pero el segmento de URL o título tiene términos de revista, consultar OpenAlex por búsqueda
        search_terms = []
        if segment:
            clean_seg = segment.replace("-", " ").replace("_", " ").strip()
            if len(clean_seg) > 3:
                search_terms.append(clean_seg)
        if page_title and len(page_title) > 3:
            search_terms.append(page_title)

        for st in search_terms:
            try:
                enc = urllib.parse.quote(st)
                oa_url = f"https://api.openalex.org/sources?search={enc}&mailto=info@thinkuy.org"
                oa_req = urllib.request.Request(oa_url, headers=config.openalex_headers("Thinkuy-EditorialRadar/1.0"))
                with urllib.request.urlopen(oa_req, timeout=3.5) as oa_res:
                    data = json.loads(oa_res.read().decode("utf-8"))
                    results = data.get("results") or []
                    if results:
                        src = results[0]
                        issn_val = src.get("issn_l") or (src.get("issn") or [None])[0]
                        if issn_val:
                            return src.get("display_name"), issn_val, src.get("country_code")
            except Exception:
                pass

        if page_title:
            return page_title, None, None

    except Exception as e:
        log.debug("Error en probe_url_for_journal_meta: %s", e)
    return None, None, None


def resolve_journal_domain_and_meta(
    query: str, db_path: str = config.DB_PATH
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Identifica la revista y SU DOMINIO CANÓNICO a partir de la consulta.

    El dominio es la unidad métrica real del Web Graph de Common Crawl; el título solo es una
    vía de resolución, nunca la unidad de medida. Orden:
      1. La consulta ES un dominio (contiene '.' y no espacios) → se usa tal cual (lo más preciso).
      2. Título/ISSN con coincidencia EXACTA normalizada en el catálogo local (sin falsos positivos
         por substring) → dominio curado (mapa explícito) o extraído de los artículos de ESA revista.
      3. Coincidencia aproximada en el catálogo (fallback defensivo).
      4. OpenAlex Sources (homepage oficial) para revistas fuera del catálogo.

    Cada meta devuelve `resolution` (proveniencia del dominio: domain_direct / curated_registry /
    catalog_url / openalex_homepage / none) y `shared_host` (aviso de atribución si el dominio
    es un portal institucional compartido).
    """
    q = query.strip()
    q_norm = norm(q)

    def _base_meta(title: str, dom: Optional[str], resolution: str, **extra) -> Dict[str, Any]:
        clean = _clean_domain(dom) if dom else None
        return {
            "journal_title": title,
            "domain": clean or "N/D",
            "issn": "N/D",
            "category": "General",
            "country": "N/D",
            "resolution": resolution,
            "shared_host": False,
            **extra,
        }

    # 1. Dominio directo: la vía más precisa (la métrica es del dominio, no del título).
    # El usuario puede pegar la URL completa (esquema, ruta, parámetros); _clean_domain la depura
    # y _split_url_scope captura el alcance de la revista dentro de portales OJS compartidos.
    if "." in q and " " not in q:
        clean_dom, journal_seg, path_prefix = _split_url_scope(q)
        if not clean_dom or clean_dom.count(".") < 1:
            return None, _base_meta(q, None, "none")
        meta = _base_meta(clean_dom, clean_dom, "domain_direct")
        meta["journal_segment"] = journal_seg
        meta["journal_path"] = path_prefix

        # Enriquecer con metadatos reales de la revista detrás de la URL/dominio
        res_t, res_issn, res_country = _probe_url_for_journal_meta(q, clean_dom, journal_seg, db_path=db_path)
        if res_t:
            meta["journal_title"] = res_t
        if res_issn:
            meta["issn"] = res_issn
        if res_country and meta["country"] == "N/D":
            meta["country"] = res_country

        return clean_dom, meta

    # 2. Título curado conocido: SOLO coincidencia EXACTA normalizada. Los títulos genéricos
    # ('Revista de Ciencias Sociales') secuestrarían consultas más largas si se admitiera
    # substring/prefijo; esas consultas se resuelven por catálogo fuzzy (con ambigüedad
    # declarada) o por OpenAlex, nunca por secuestro silencioso.
    matched_domain = None
    for key, dom in KNOWN_JOURNAL_DOMAINS.items():
        if q_norm == norm(key):
            matched_domain = dom
            break

    conn = _get_db_conn(db_path)
    try:
        # 3a. Coincidencia EXACTA normalizada en journals (título o ISSN).
        row = conn.execute(
            """SELECT title, issn_online, issn_print, country, subject_areas
               FROM journals
               WHERE norm(title) = ?
                  OR LOWER(issn_online) = ?
                  OR LOWER(issn_print) = ?
               LIMIT 1""",
            (q_norm, q.lower(), q.lower()),
        ).fetchone()
        fuzzy_candidates: List[str] = []
        fuzzy_used = False
        if not row:
            # 3b. Fuzzy defensivo: recopilar TODAS las candidatas; si hay varias, es una
            # consulta ambigua y se declara (nunca se elige al azar ni se oculta).
            frows = conn.execute(
                """SELECT DISTINCT title FROM journals WHERE norm(title) LIKE ? LIMIT 8""",
                (f"%{q_norm}%",),
            ).fetchall()
            fuzzy_candidates = [r["title"] for r in frows]
            if fuzzy_candidates:
                best = min(fuzzy_candidates, key=lambda t: edit_distance(norm(t), q_norm))
                row = conn.execute(
                    """SELECT title, issn_online, issn_print, country, subject_areas
                       FROM journals WHERE norm(title) = ? LIMIT 1""",
                    (norm(best),),
                ).fetchone()
                fuzzy_used = True

        if row:
            j_title = row["title"]
            found_dom = matched_domain
            resolution = "curated_registry" if found_dom else None
            if not found_dom:
                art_row = conn.execute(
                    """SELECT url, pdf_url FROM articles
                       WHERE norm(journal_title) = norm(?) AND (url IS NOT NULL OR pdf_url IS NOT NULL)
                       LIMIT 1""",
                    (j_title,),
                ).fetchone()
                if art_row:
                    url_candidate = art_row["url"] or art_row["pdf_url"] or ""
                    parsed = urllib.parse.urlparse(url_candidate)
                    if parsed.netloc and "doi.org" not in parsed.netloc:
                        found_dom = _clean_domain(parsed.netloc)
                        resolution = "catalog_url"
            if not found_dom:
                oa_dom, _ = _resolve_journal_domain_openalex(j_title)
                if oa_dom:
                    found_dom = oa_dom
                    resolution = "openalex_homepage"
            issn_val = row["issn_online"] or row["issn_print"] or "N/D"
            meta = _base_meta(
                j_title, found_dom, resolution or "none",
                issn=issn_val,
                category=row["subject_areas"] or "Ciencias Sociales y Humanidades",
                country=row["country"] or "N/D",
            )
            if fuzzy_used and meta.get("resolution") != "curated_registry":
                meta["resolution"] = "fuzzy_catalog"
            if len(fuzzy_candidates) > 1:
                meta["ambiguous"] = True
                meta["ambiguous_matches"] = fuzzy_candidates[:8]
            if found_dom:
                meta["shared_host"] = _detect_shared_host(conn, meta["domain"])
            return found_dom, meta

        # 3c. Artículos del catálogo por título (exacto primero; fuzzy con ambigüedad declarada).
        art_rows = conn.execute(
            """SELECT journal_title, issn, url FROM articles
               WHERE norm(journal_title) = ? LIMIT 1""",
            (q_norm,),
        ).fetchall()
        art_fuzzy: List[str] = []
        if not art_rows:
            afrows = conn.execute(
                """SELECT DISTINCT journal_title, MIN(url) url FROM articles
                   WHERE norm(journal_title) LIKE ? GROUP BY journal_title LIMIT 8""",
                (f"%{q_norm}%",),
            ).fetchall()
            art_fuzzy = [r["journal_title"] for r in afrows]
            if art_fuzzy:
                best = min(art_fuzzy, key=lambda t: edit_distance(norm(t), q_norm))
                art_rows = conn.execute(
                    """SELECT journal_title, issn, url FROM articles
                       WHERE norm(journal_title) = ? LIMIT 1""",
                    (norm(best),),
                ).fetchall()
        art_match = art_rows[0] if art_rows else None
        if art_match and art_match["journal_title"]:
            j_title = art_match["journal_title"]
            found_dom = matched_domain
            resolution = "curated_registry" if found_dom else None
            if not found_dom:
                url_candidate = art_match["url"] or ""
                parsed = urllib.parse.urlparse(url_candidate)
                if parsed.netloc and "doi.org" not in parsed.netloc:
                    found_dom = _clean_domain(parsed.netloc)
                    resolution = "catalog_url"
            if not found_dom:
                oa_dom, _ = _resolve_journal_domain_openalex(j_title)
                if oa_dom:
                    found_dom = oa_dom
                    resolution = "openalex_homepage"
            meta = _base_meta(
                j_title, found_dom, resolution or "none",
                issn=art_match["issn"] or "N/D",
                category="Comunicación y Humanidades",
            )
            if art_fuzzy and meta.get("resolution") != "curated_registry":
                meta["resolution"] = "fuzzy_catalog"
            if len(art_fuzzy) > 1:
                meta["ambiguous"] = True
                meta["ambiguous_matches"] = art_fuzzy[:8]
            if found_dom:
                meta["shared_host"] = _detect_shared_host(conn, meta["domain"])
            return found_dom, meta

        # 4. Registro global abierto (OpenAlex Sources) para cualquier revista del mundo.
        # El dominio curado (mapa explícito) tiene prioridad sobre el homepage de OpenAlex.
        oa_dom, oa_meta = _resolve_journal_domain_openalex(q)
        if oa_dom or oa_meta or matched_domain:
            final_dom = matched_domain or oa_dom
            return final_dom, _base_meta(
                oa_meta.get("journal_title") or q.title(),
                final_dom,
                "curated_registry" if matched_domain else ("openalex_homepage" if oa_dom else "none"),
                issn=oa_meta.get("issn") or "N/D",
                category=oa_meta.get("category") or "General",
                country=oa_meta.get("country") or "N/D",
                publisher=oa_meta.get("publisher") or "N/D",
                global_works=oa_meta.get("global_works"),
                global_cites=oa_meta.get("global_cites"),
                h_index=oa_meta.get("h_index"),
                is_oa=oa_meta.get("is_oa", False),
            )

        return matched_domain, _base_meta(
            q.title(), matched_domain, "curated_registry" if matched_domain else "none"
        )
    finally:
        conn.close()

