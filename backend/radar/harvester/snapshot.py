"""Dumps masivos: OpenAlex snapshot en S3 (data/jsonl/works/updated_date=*/part_*.gz).

Patrón de escalado recomendado: en lugar de rascar la API obra por obra, se baja el
snapshot mensual y se filtra localmente por ISSN. El descubrimiento de particiones se
hace vía `manifest.json` (que se escribe al final: si existe, el dataset está completo).

El snapshot completo (~330 GB comprimidos) es una decisión de infraestructura; este
módulo aporta el plumbing: leer el manifest, listar/verificar particiones y descargar
una ventana filtrada por ISSN del catálogo (streaming, partición por partición).
"""
from __future__ import annotations

import gzip
import io
import json
import logging

import httpx

from ..normalize import year_of
from .base import Article

log = logging.getLogger("radar.snapshot")

S3_BASE = "https://openalex.s3.amazonaws.com"
WORKS_MANIFEST = f"{S3_BASE}/data/jsonl/works/manifest.json"


def _https(url: str) -> str:
    """Convierte s3://openalex/data/... en https://openalex.s3.amazonaws.com/data/..."""
    if url.startswith("s3://"):
        url = url[len("s3://"):]
        bucket, _, rest = url.partition("/")
        return f"https://{bucket}.s3.amazonaws.com/{rest}"
    return url


def fetch_manifest(http: httpx.Client) -> dict:
    """Descarga el manifest de works. Contiene files[] con url y meta (record_count)."""
    try:
        resp = http.get(WORKS_MANIFEST, timeout=45)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning("OpenAlex snapshot manifest: %s", e)
        return {}


def list_partitions(http: httpx.Client, max_parts: int | None = None) -> list[dict]:
    """Lista las particiones (archivos) del snapshot de works."""
    m = fetch_manifest(http)
    files = m.get("files") or []
    if max_parts:
        files = files[:max_parts]
    out = []
    for f in files:
        url = _https(f.get("url", ""))
        meta = f.get("meta") or {}
        out.append({
            "url": url,
            "content_length": meta.get("content_length"),
            "record_count": meta.get("record_count"),
            "date": m.get("date"),
        })
    return out


def check_snapshot(http: httpx.Client) -> dict:
    """Verifica disponibilidad del snapshot (manifest + primera partición)."""
    m = fetch_manifest(http)
    if not m:
        return {"ok": False, "detail": "manifest no disponible"}
    files = m.get("files") or []
    if not files:
        return {"ok": False, "detail": "manifest sin archivos"}
    url = _https(files[0].get("url", ""))
    try:
        r = http.get(url, headers={"Range": "bytes=0-0"}, timeout=30)
        reachable = r.status_code in (200, 206)
    except Exception:
        reachable = False
    return {
        "ok": reachable,
        "record_count": m.get("record_count"),
        "date": m.get("date"),
        "partitions": len(files),
        "sample_url": url,
    }


def stream_works(http: httpx.Client, url: str) -> list[dict]:
    """Descarga y descomprime una partición completa (ventanas pequeñas)."""
    try:
        resp = http.get(url, timeout=180)
        resp.raise_for_status()
    except Exception as e:
        log.warning("Snapshot %s: %s", url, e)
        return []
    out: list[dict] = []
    try:
        with gzip.open(io.BytesIO(resp.content), "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        log.warning("Snapshot %s descomprime: %s", url, e)
    return out


def works_to_articles(works: list[dict], issn_set: set[str] | None = None,
                      date_from: str | None = None) -> list[Article]:
    """Convierte works del snapshot en Article, filtrando por ISSN y ventana."""
    issn_set = {i.replace("-", "").upper() for i in (issn_set or set())}
    out: list[Article] = []
    for w in works:
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        issns = [i.replace("-", "").upper() for i in (src.get("issn") or [])]
        if issn_set and not (set(issns) & issn_set):
            continue
        pub_date = (w.get("publication_date") or "")[:10] or None
        if date_from and pub_date and pub_date < date_from:
            continue
        authors = []
        for au in (w.get("authorships") or [])[:40]:
            a = au.get("author") or {}
            nm = a.get("display_name") or ""
            parts = nm.strip().split()
            authors.append({"family": parts[-1] if parts else "", "given": " ".join(parts[:-1])})
        out.append(Article(
            title=w.get("title") or "",
            doi=(w.get("doi") or "").replace("https://doi.org/", "").strip().lower() or None,
            abstract=None,
            keywords=[c.get("display_name") for c in (w.get("concepts") or []) if c.get("score", 0) >= 0.5][:10],
            authors=authors,
            journal_title=src.get("display_name"),
            issn=(src.get("issn") or [None])[0],
            year=year_of(pub_date),
            pub_date=pub_date,
            lang="es",
            url=w.get("doi"),
            source="openalex",
            source_id=w.get("id"),
            access="oa" if (w.get("open_access") or {}).get("is_oa") else "closed",
            cited_by=w.get("cited_by_count") or 0,
            openalex_id=w.get("id"),
            referenced_ids=[r.get("id") for r in (w.get("referenced_works") or [])],
        ))
    return out


def ingest_window(http: httpx.Client, issn_set: set[str], max_parts: int = 5,
                  date_from: str | None = None) -> tuple[list[Article], dict]:
    """Descarga hasta `max_parts` particiones y filtra por ISSN. Devuelve (artículos, stats)."""
    parts = list_partitions(http, max_parts=max_parts)
    articles: list[Article] = []
    scanned = 0
    for p in parts:
        works = stream_works(http, p["url"])
        scanned += len(works)
        articles.extend(works_to_articles(works, issn_set=issn_set, date_from=date_from))
        log.info("Snapshot part: %d works (%d coinciden ISSN)", len(works), len(articles))
    return articles, {"partitions": len(parts), "scanned": scanned, "matched": len(articles)}