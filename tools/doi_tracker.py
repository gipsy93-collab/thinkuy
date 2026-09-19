#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doi_tracker.py — Rastreador de menciones web de DOIs (sin APIs comerciales).

Para cada DOI consulta fuentes abiertas y guarda la serie temporal en SQLite:
  - Hacker News (Algolia API, sin key)
  - Wikipedia (EN + ES, sin key)
  - Hypothes.is (anotaciones publicas, sin key)
  - StackExchange (sin key, con descompresion GZIP)
  - Wayback Machine CDX (historial de capturas del DOI)
  - Crossref (citas academicas, polite pool)
  - DataCite (citas y preprints arXiv)
  - OpenAlex (citas academicas + OA, sin key)
  - Altmetric Public Badge (score, tweets, noticias y politicas publicas)

Uso:
  python doi_tracker.py 10.48550/arXiv.1706.03762
  python doi_tracker.py --list doids.txt
  python doi_tracker.py --db data/doi_tracker.db 10.1038/nature12373

Tabla creada: doi_events(doi, source, count, detail, checked_at)
  -> Serie temporal por (doi, source) para ver como se mueve un paper.
"""
import argparse
import gzip
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = "radar-obcc/1.0 (rastreo de menciones DOI; mailto:investigacion@example.com)"
DB_PATH = "data/doi_tracker.db"


def clean_doi(doi: str) -> str:
    """Limpia URLs, prefijos y espacios para dejar solo el formato canonico 10.xxxx/..."""
    if not doi:
        return ""
    doi = doi.strip()
    match = re.search(r"(10\.\d{4,9}/[^\s]+)", doi, re.IGNORECASE)
    if match:
        return match.group(1).rstrip("/.,;)")
    return doi


def get_json(url, timeout=30, headers=None):
    """Realiza peticion HTTP con User-Agent y soporte automatico para GZIP."""
    h = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw_data = r.read()
        is_gzip = r.headers.get("Content-Encoding") == "gzip" or (
            len(raw_data) >= 2 and raw_data[:2] == b"\x1f\x8b"
        )
        if is_gzip:
            raw_data = gzip.decompress(raw_data)
        return json.loads(raw_data.decode("utf-8", "replace"))


def hn_mentions(doi):
    """Hacker News via Algolia. Busca el DOI completo y, si es arXiv, el id."""
    queries = []
    if "arxiv" in doi.lower():
        queries.append(doi.split("/")[-1])  # id arxiv ej. 1706.03762
    queries.append(doi)
    total = 0
    detail = []
    for q in queries:
        try:
            d = get_json(
                "https://hn.algolia.com/api/v1/search?query="
                + urllib.parse.quote(q)
                + "&hitsPerPage=10&tags=story"
            )
            total = max(total, d.get("nbHits", 0))
            for h in d.get("hits", [])[:5]:
                detail.append({
                    "title": (h.get("title") or "")[:80],
                    "date": h.get("created_at", ""),
                    "url": (h.get("url") or "")[:120],
                })
        except Exception as e:
            detail.append({"error": str(e)[:100]})
        time.sleep(0.2)
    # Dedupe por titulo
    seen, uniq = set(), []
    for x in detail:
        k = x.get("title")
        if k and k not in seen:
            seen.add(k)
            uniq.append(x)
    return total, uniq[:5]


def wikipedia_mentions(doi):
    """Wikipedia: consulta exacta en Wikipedia en Ingles (en) y Espanol (es)."""
    queries = [doi]
    if "arxiv" in doi.lower():
        queries.append(doi.split("/")[-1])

    best_total = 0
    all_details = []

    for lang in ["en", "es"]:
        # 1. Indice de enlaces externos
        try:
            url_ext = (
                f"https://{lang}.wikipedia.org/w/api.php?action=query&list=exturlusage"
                f"&euquery={urllib.parse.quote('doi.org/' + doi, safe='/')}&format=json&eulimit=10"
            )
            d_ext = get_json(url_ext)
            if d_ext and isinstance(d_ext, dict):
                hits = d_ext.get("query", {}).get("exturlusage", [])
                for h in hits:
                    title = h.get("title", "")
                    if title:
                        all_details.append({
                            "wiki": lang.upper(),
                            "title": title,
                            "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                            "snippet": f"Citado como enlace externo en {title}",
                        })
        except Exception:
            pass

        # 2. Busqueda de texto con comillas exactas
        for q in queries:
            try:
                exact_query = f'"{q}"'
                url = (
                    f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search"
                    f"&srsearch={urllib.parse.quote(exact_query)}&format=json&srlimit=5"
                )
                d = get_json(url)
                if d and isinstance(d, dict):
                    res = d.get("query", {}).get("search", [])
                    total_hits = d.get("query", {}).get("searchinfo", {}).get("totalhits", len(res))
                    best_total += total_hits
                    for x in res:
                        all_details.append({
                            "wiki": lang,
                            "title": x.get("title"),
                            "snippet": (x.get("snippet") or "")[:100],
                        })
            except Exception as e:
                all_details.append({"wiki": lang, "error": str(e)[:100]})
            time.sleep(0.15)

    # Dedupe por pagina
    seen, uniq = set(), []
    for it in all_details:
        key = (it.get("wiki"), it.get("title"))
        if it.get("title") and key not in seen:
            seen.add(key)
            uniq.append(it)

    return len(uniq), uniq[:5]


def hypothesis_mentions(doi):
    """Hypothes.is: anotaciones publicas que citan el paper (varias URIs)."""
    uris = ["https://doi.org/" + doi]
    if "arxiv" in doi.lower():
        aid = doi.split("/")[-1]
        uris += ["https://arxiv.org/abs/" + aid, "https://arxiv.org/pdf/" + aid]
    best_total, best_detail = 0, []
    for u in uris:
        try:
            d = get_json(
                "https://api.hypothes.is/api/search?limit=10&uri="
                + urllib.parse.quote(u)
            )
            rows = d.get("rows", [])
            total = d.get("total", len(rows))
            if total > best_total:
                best_total = total
                best_detail = [{
                    "title": (a.get("title") or a.get("uri") or "")[:100],
                    "user": a.get("user", "")[:40],
                } for a in rows[:5]]
        except Exception as e:
            best_detail = [{"error": str(e)[:100]}]
        time.sleep(0.2)
    return best_total, best_detail


def stackexchange_mentions(doi):
    """StackOverflow y StackExchange: preguntas que referencian el DOI."""
    queries = []
    if "arxiv" in doi.lower():
        queries.append(doi.split("/")[-1])
    queries.append(doi)
    best_total, best_detail = 0, []
    for q in queries:
        try:
            d = get_json(
                "https://api.stackexchange.com/2.3/search/excerpts?q="
                + urllib.parse.quote(q)
                + "&site=stackoverflow&pagesize=5"
            )
            items = d.get("items", [])
            total = d.get("total")
            if total is None:
                total = len(items)
            if total > best_total:
                best_total = total
                best_detail = [{"title": (it.get("title") or "")[:100]} for it in items[:5]]
        except Exception as e:
            best_detail = [{"error": str(e)[:100]}]
        time.sleep(0.2)
    return best_total, best_detail


def wayback_captures(doi):
    """Wayback Machine CDX: historial de capturas del resolver del DOI."""
    try:
        d = get_json(
            "http://web.archive.org/cdx/search/cdx?url="
            + urllib.parse.quote("doi.org/" + doi, safe="/")
            + "&matchType=prefix&output=json&fl=timestamp,statuscode&limit=1000"
        )
        if not d or not isinstance(d, list) or len(d) < 2:
            return 0, []
        rows = d[1:]
        detail = [{"ts": r[0], "status": r[1]} for r in rows[:5]]
        return len(rows), detail
    except Exception as e:
        return 0, [{"error": str(e)[:100]}]


def crossref_citations(doi):
    """Crossref: citas academicas indexadas (los DOI arXiv no estan aqui)."""
    try:
        d = get_json("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/"))
        m = d.get("message", {})
        return m.get("is-referenced-by-count", 0), [{"title": (m.get("title") or [""])[0][:100]}]
    except Exception:
        return 0, [{"info": "DOI no registrado en Crossref (comun en arXiv/DataCite)"}]


def datacite_citations(doi):
    """DataCite: citas y metadatos (cubre arXiv, preprints y datos)."""
    try:
        d = get_json("https://api.datacite.org/dois/" + urllib.parse.quote(doi, safe=""))
        a = d.get("data", {}).get("attributes", {})
        citation_count = a.get("citationCount")
        if citation_count is None:
            cit = a.get("citations") or []
            citation_count = len(cit)
        return citation_count, [{
            "title": (a.get("titles") or [{}])[0].get("title", "")[:100],
            "citations": citation_count,
        }]
    except Exception as e:
        return 0, [{"error": str(e)[:100]}]


def openalex_info(doi):
    """OpenAlex: citas, OA y existencia (formato canonico https://doi.org/...)."""
    try:
        canonical_doi = "https://doi.org/" + doi
        url = (
            "https://api.openalex.org/works?filter=doi:"
            + urllib.parse.quote(canonical_doi, safe="")
        )
        d = get_json(url)
        res = d.get("results", [])
        if not res:
            return 0, {"info": "DOI no indexado en OpenAlex"}
        w = res[0]
        return w.get("cited_by_count", 0), {
            "title": (w.get("title") or "")[:120],
            "is_oa": (w.get("open_access") or {}).get("is_oa"),
            "year": w.get("publication_year"),
        }
    except Exception as e:
        return 0, {"error": str(e)[:100]}


def altmetric_summary(doi):
    """Altmetric Public Endpoint: puntuacion, menciones en Twitter, noticias y politicas publicas."""
    try:
        url = "https://api.altmetric.com/v1/doi/" + urllib.parse.quote(doi, safe="")
        d = get_json(url)
        score = int(round(d.get("score", 0)))
        detail = {
            "score": d.get("score"),
            "tweets": d.get("cited_by_tweeters_count", 0),
            "news_msm": d.get("cited_by_msm_count", 0),
            "policies": d.get("cited_by_policies_count", 0),
            "wikipedia": d.get("cited_by_wikipedia_count", 0),
        }
        return score, detail
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 0, {"info": "Sin registro publico en Altmetric"}
        return 0, {"error": f"HTTP {e.code}"}
    except Exception as e:
        return 0, {"error": str(e)[:100]}


TRANSMEDIA_FEEDS = [
    ("Revista Panamericana de Pedagogía", "https://revpanamericanadepedagogia.substack.com/feed"),
]


def transmedia_mentions(doi):
    """Rastreo en blogs y newsletters científicas transmedia (Substack, Medium)."""
    import xml.etree.ElementTree as ET
    doi_norm = doi.lower().strip()
    doi_tail = doi_norm.split("/")[-1] if "/" in doi_norm else doi_norm
    matches = []
    seen = set()

    for pub_name, feed_url in TRANSMEDIA_FEEDS:
        try:
            req = urllib.request.Request(feed_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=12) as r:
                root = ET.fromstring(r.read())
                for item in root.findall(".//item"):
                    i_title = (item.find("title").text if item.find("title") is not None else "") or ""
                    i_link = (item.find("link").text if item.find("link") is not None else "") or ""
                    i_date = (item.find("pubDate").text if item.find("pubDate") is not None else "") or ""
                    i_desc = (item.find("description").text if item.find("description") is not None else "") or ""
                    i_content = ""
                    for child in item:
                        if "encoded" in child.tag:
                            i_content = child.text or ""

                    full_text = f"{i_title} {i_desc} {i_content}".lower()

                    if (
                        doi_norm in full_text
                        or (len(doi_tail) >= 4 and f"/{doi_tail}" in full_text)
                        or f"rpp.{doi_tail}" in full_text
                        or f"view/{doi_tail}" in full_text
                    ):
                        if i_link not in seen:
                            seen.add(i_link)
                            clean_snippet = re.sub(r"<[^>]+>", " ", i_desc or i_content).strip()
                            clean_snippet = " ".join(clean_snippet.split())[:160]
                            matches.append({
                                "platform": "Substack" if "substack" in feed_url else "Blog/Newsletter",
                                "publication": pub_name,
                                "title": i_title,
                                "url": i_link,
                                "date": i_date,
                                "snippet": clean_snippet,
                            })
        except Exception as e:
            matches.append({"error": str(e)[:100]})

    return len(matches), matches


SOURCES = [
    ("transmedia", transmedia_mentions),
    ("altmetric", altmetric_summary),
    ("hackernews", hn_mentions),
    ("wikipedia", wikipedia_mentions),
    ("hypothesis", hypothesis_mentions),
    ("stackexchange", stackexchange_mentions),
    ("wayback", wayback_captures),
    ("crossref", crossref_citations),
    ("datacite", datacite_citations),
    ("openalex", openalex_info),
]


def track(raw_doi, db_path):
    doi = clean_doi(raw_doi)
    if not doi:
        print(f"Error: DOI invalido '{raw_doi}'")
        return None

    # Asegurar directorio de base de datos
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS doi_events(
            doi TEXT, source TEXT, count INTEGER, detail TEXT,
            checked_at TEXT, PRIMARY KEY(doi, source, checked_at))"""
    )
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"\n== DOI: {doi}  [{now}] ==")
    for name, fn in SOURCES:
        try:
            count, detail = fn(doi)
        except Exception as e:
            count, detail = 0, {"error": str(e)[:100]}
        conn.execute(
            "INSERT OR REPLACE INTO doi_events(doi,source,count,detail,checked_at)"
            " VALUES(?,?,?,?,?)",
            (doi, name, count, json.dumps(detail, ensure_ascii=False), now),
        )
        conn.commit()
        print(f"  {name:<14} -> {count}")
        if count == 0 and detail and isinstance(detail, list) and len(detail) > 0 and isinstance(detail[0], dict) and detail[0].get("error"):
            print(f"    (error: {detail[0]['error']})")
        time.sleep(0.3)
    conn.close()
    return now


def main():
    ap = argparse.ArgumentParser(description="Rastreador de menciones web de DOIs")
    ap.add_argument("--db", default=DB_PATH, help="ruta al sqlite")
    ap.add_argument("--list", help="archivo con un DOI por linea")
    ap.add_argument("doids", nargs="*", help="uno o mas DOIs")
    args = ap.parse_args()

    doids = list(args.doids)
    if args.list:
        with open(args.list, encoding="utf-8") as f:
            doids += [line.strip() for line in f if line.strip()]

    if not doids:
        ap.error("se requiere al menos un DOI o --list")

    for doi in doids:
        track(doi, args.db)
    print("\nListo. Consultas: sqlite3 %s 'SELECT * FROM doi_events ORDER BY checked_at DESC LIMIT 10;'" % args.db)


if __name__ == "__main__":
    sys.exit(main())