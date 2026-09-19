# -*- coding: utf-8 -*-
"""Consultas a la API CDX y rankings WebGraph de Common Crawl."""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .. import config, db
from .common import (
    log,
    _CC_COLLECTION_CACHE,
    _CC_COLLECTION_LOCK,
    CC_DOMAIN_RANKS_DB,
    CC_INLINKS_DB,
    CC_RANKS_GZ,
    CC_RELEASE_ID,
    _clean_domain,
    _domain_candidates,
    _cc_total_domains,
    _iter_history_releases,
    _get_db_conn,
)

def get_latest_common_crawl_collection() -> Dict[str, Any]:
    """Obtiene la última colección activa de Common Crawl desde su API oficial."""
    global _CC_COLLECTION_CACHE
    with _CC_COLLECTION_LOCK:
        if _CC_COLLECTION_CACHE and (time.time() - _CC_COLLECTION_CACHE.get("_fetched_at", 0) < 86400):
            return _CC_COLLECTION_CACHE

        url = "https://index.commoncrawl.org/collinfo.json"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Thinkuy/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                colls = json.loads(r.read().decode("utf-8"))
                if colls:
                    latest = colls[0]
                    latest["_fetched_at"] = time.time()
                    _CC_COLLECTION_CACHE = latest
                    return latest
        except Exception as e:
            log.warning("No se pudo conectar con Common Crawl collinfo: %s", e)

        return {
            "id": "CC-MAIN-2026-34",
            "name": "August 2026 Index",
            "cdx-api": "https://index.commoncrawl.org/CC-MAIN-2026-34-index",
        }


def query_common_crawl_domain_real(domain: str, scope_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Consulta en tiempo real la API de índice CDX de Common Crawl para un dominio.
    Devuelve datos 100% verificados sin simulaciones: capturas reales, URLs y fechas.

    Si se proporciona `scope_path` (p. ej. 'index.php/sophia'), consulta primero las capturas
    del alcance de la revista dentro del portal; si no hay, cae al nivel del portal completo
    y lo señala con una nota (host OJS compartido).
    """
    if not domain or domain == "N/D":
        return {
            "verified": False,
            "status": "Dominio no especificado",
            "error": "No se proporcionó un dominio web para auditar en Common Crawl.",
        }

    clean_dom = _clean_domain(domain)

    coll = get_latest_common_crawl_collection()
    coll_id = coll.get("id", "CC-MAIN-2026-34")
    coll_name = coll.get("name", "August 2026 Index")
    cdx_api = coll.get("cdx-api") or f"https://index.commoncrawl.org/{coll_id}-index"

    def _do_cdx_query(target_domain: str, api_url: str, path_suffix: str = "") -> Optional[Dict[str, Any]]:
        if path_suffix:
            url = f"{api_url}?url={target_domain}/{path_suffix}*&output=json&limit=15"
        else:
            url = f"{api_url}?url={target_domain}/*&output=json&limit=15"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Thinkuy/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read().decode("utf-8").strip()
                lines = [json.loads(l) for l in raw.split("\n") if l]
                sample_urls = [x.get("url") for x in lines if x.get("url")][:8]
                latest_ts = lines[0].get("timestamp") if lines else None
                warc_file = lines[0].get("filename") if lines else None

                readable_date = "N/D"
                if latest_ts and len(latest_ts) >= 12:
                    readable_date = f"{latest_ts[:4]}-{latest_ts[4:6]}-{latest_ts[6:8]} {latest_ts[8:10]}:{latest_ts[10:12]} UTC"
                elif latest_ts and len(latest_ts) >= 8:
                    readable_date = f"{latest_ts[:4]}-{latest_ts[4:6]}-{latest_ts[6:8]}"

                return {
                    "verified": True,
                    "domain": target_domain,
                    "collection": coll_id,
                    "collection_name": coll_name,
                    "sample_captures_count": len(lines),
                    "sample_urls": sample_urls,
                    "latest_crawl_date": readable_date,
                    "sample_warc_file": warc_file,
                    "status": "Indexado en Common Crawl" if lines else "Sin capturas en la colección activa",
                }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {
                    "verified": True,
                    "domain": target_domain,
                    "collection": coll_id,
                    "collection_name": coll_name,
                    "sample_captures_count": 0,
                    "sample_urls": [],
                    "latest_crawl_date": "N/D",
                    "sample_warc_file": None,
                    "status": "No detectado en la colección activa de Common Crawl",
                }
            log.warning("HTTP %d consultando Common Crawl CDX para %s", e.code, target_domain)
            return None
        except Exception as e:
            log.warning("Error consultando Common Crawl CDX para %s: %s", target_domain, e)
            return None

    # Si hay alcance de revista (ruta OJS), consultar primero ese subconjunto del portal.
    if scope_path:
        scope_res = _do_cdx_query(clean_dom, cdx_api, path_suffix=scope_path)
        if scope_res and scope_res.get("sample_captures_count", 0) > 0:
            scope_res["note"] = (
                f"Capturas del alcance '{scope_path}' de la revista dentro del portal compartido."
            )
            return scope_res

    # Intentar con la colección actual (nivel de dominio/portal)
    res = _do_cdx_query(clean_dom, cdx_api)
    if res:
        # Si no hubo capturas en el subdominio y es un subdominio profundo (ej. revistapanamericanadecomunicacion.up.edu.mx)
        # verificar si el host institucional o revistas.* sí tiene capturas
        if res.get("sample_captures_count") == 0 and clean_dom.count(".") >= 3:
            parts = clean_dom.split(".")
            parent_dom = ".".join(parts[-3:])  # ej. up.edu.mx
            revistas_dom = f"revistas.{parent_dom}"
            parent_res = _do_cdx_query(revistas_dom, cdx_api)
            if parent_res and parent_res.get("sample_captures_count", 0) > 0:
                parent_res["note"] = f"El subdominio específico no arrojó capturas, pero el repositorio institucional ({revistas_dom}) sí está indexado."
                return parent_res
        return res

    # Si la API principal dio 502/error temporal, intentar con la colección estable previa
    fallback_coll = "CC-MAIN-2024-51"
    fallback_api = f"https://index.commoncrawl.org/{fallback_coll}-index"
    res_fallback = _do_cdx_query(clean_dom, fallback_api)
    if res_fallback:
        res_fallback["collection"] = fallback_coll
        res_fallback["collection_name"] = "December 2024 Index (Fallback)"
        return res_fallback

    return {
        "verified": False,
        "domain": clean_dom,
        "collection": coll_id,
        "collection_name": coll_name,
        "sample_captures_count": 0,
        "sample_urls": [],
        "latest_crawl_date": "N/D",
        "sample_warc_file": None,
        "status": "Servicio de Common Crawl CDX temporalmente inaccesible",
        "error": "No se pudo establecer conexión con los clústeres de Common Crawl.",
    }



def get_common_crawl_harmonic_centrality(domain: str) -> Dict[str, Any]:
    """
    Obtiene la Centralidad Armónica y PageRank oficiales de Common Crawl
    desde la base de datos indexada del release activo (config.CC_RANKS_DB).
    """
    if not domain or domain == "N/D":
        return {
            "available": False,
            "status": "Dominio no provisto para la consulta",
            "harmonic_val": None,
            "harmonic_rank": None,
            "pagerank_val": None,
            "pagerank_rank": None,
        }

    clean_dom = _clean_domain(domain)
    candidates_norm = _domain_candidates(clean_dom)
    candidates_rev = [".".join(reversed(c.split("."))) for c in candidates_norm]

    if not os.path.exists(CC_DOMAIN_RANKS_DB):
        is_downloading = os.path.exists(CC_RANKS_GZ)
        return {
            "available": False,
            "status": "Descargando e indexando el dataset oficial de Common Crawl (~2.2 GB)..." if is_downloading else "Dataset no instalado",
            "harmonic_val": None,
            "harmonic_rank": None,
            "pagerank_val": None,
            "pagerank_rank": None,
        }

    try:
        conn = sqlite3.connect(CC_DOMAIN_RANKS_DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        row = None
        for cand_norm, cand_rev in zip(candidates_norm, candidates_rev):
            row = c.execute(
                """SELECT domain_rev, domain_norm, harmonic_rank, harmonic_val, pagerank_rank, pagerank_val, n_hosts
                   FROM cc_ranks
                   WHERE domain_norm = ?
                   LIMIT 1""",
                (cand_norm,)
            ).fetchone()
            if not row:
                row = c.execute(
                    """SELECT domain_rev, domain_norm, harmonic_rank, harmonic_val, pagerank_rank, pagerank_val, n_hosts
                       FROM cc_ranks
                       WHERE domain_rev = ?
                       LIMIT 1""",
                    (cand_rev,)
                ).fetchone()
            if row:
                break
        conn.close()

        if row:
            total_domains = _cc_total_domains(CC_DOMAIN_RANKS_DB) or 58_900_000
            escalated = row["domain_norm"] != candidates_norm[0]
            return {
                "available": True,
                "domain_matched": row["domain_norm"],
                "domain_rev": row["domain_rev"],
                "harmonic_val": row["harmonic_val"],
                "harmonic_rank": row["harmonic_rank"],
                "pagerank_val": row["pagerank_val"],
                "pagerank_rank": row["pagerank_rank"],
                "n_hosts": row["n_hosts"],
                "release": CC_RELEASE_ID,
                "total_domains": total_domains,
                # Atribución explícita: la métrica puede corresponder a un ancestro del
                # dominio consultado (p. ej. ugca.edu.co para revistas.ugca.edu.co), porque
                # el Web Graph de Common Crawl agrega a nivel de dominio registrable (PLD).
                "attribution": {
                    "level": "escalated" if escalated else "exact",
                    "queried": candidates_norm[0],
                    "matched": row["domain_norm"],
                    "note": (
                        f"La métrica corresponde a '{row['domain_norm']}' (ancestro del dominio "
                        f"consultado '{candidates_norm[0]}'), no a la revista aislada."
                        if escalated else "Métrica del dominio exacto consultado."
                    ),
                },
                "source": f"Common Crawl Web Graph Oficial (Release {CC_RELEASE_ID})",
            }
        else:
            return {
                "available": False,
                "status": "Dominio no listado en el ranking de dominios principales de Common Crawl",
                "harmonic_val": None,
                "harmonic_rank": None,
                "pagerank_val": None,
                "pagerank_rank": None,
            }
    except Exception as e:
        log.error("Error consultando %s: %s", CC_DOMAIN_RANKS_DB, e)
        return {
            "available": False,
            "status": f"Error consultando índice de centralidad: {e}",
            "harmonic_val": None,
            "harmonic_rank": None,
            "pagerank_val": None,
            "pagerank_rank": None,
        }


def get_cc_history_trajectory(clean_dom: str) -> List[Dict[str, Any]]:
    """Serie temporal REAL de rankings del dominio a través de los releases históricos
    indexados en CC_HISTORY_DIR. Cada punto corresponde a un release oficial del WebGraph
    de Common Crawl; no se interpola ningún valor faltante."""
    if not clean_dom or clean_dom == "n/d":
        return []
    candidates = _domain_candidates(clean_dom)
    candidates_rev = [".".join(reversed(c.split("."))) for c in candidates]
    trajectory: List[Dict[str, Any]] = []
    for release_id, db_path, _sort in _iter_history_releases():
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = None
            for cand_norm, cand_rev in zip(candidates, candidates_rev):
                row = conn.execute(
                    """SELECT domain_norm, harmonic_rank, harmonic_val, pagerank_rank, pagerank_val
                       FROM cc_ranks WHERE domain_norm = ? LIMIT 1""",
                    (cand_norm,),
                ).fetchone()
                if not row:
                    row = conn.execute(
                        """SELECT domain_norm, harmonic_rank, harmonic_val, pagerank_rank, pagerank_val
                           FROM cc_ranks WHERE domain_rev = ? LIMIT 1""",
                        (cand_rev,),
                    ).fetchone()
                if row:
                    break
            conn.close()
        except Exception as e:
            log.warning("Error consultando release histórico %s: %s", release_id, e)
            continue
        if row:
            trajectory.append({
                "release": release_id,
                "period": release_id,
                "domain_matched": row["domain_norm"],
                "harmonic_rank": row["harmonic_rank"],
                "harmonic_val": row["harmonic_val"],
                "pagerank_rank": row["pagerank_rank"],
                "pagerank_val": row["pagerank_val"],
                "source": "Common Crawl Web Graph Oficial",
            })
    return trajectory


def get_real_referrers(domain: str, limit: int = 10) -> Dict[str, Any]:
    """Dominios que enlazan a la revista, calculados sobre el grafo real de Common Crawl
    (herramienta `tools/build_cc_inlinks.py`, base CC_INLINKS_DB)."""
    clean_dom = _clean_domain(domain) if domain else ""
    if not clean_dom or clean_dom == "n/d":
        return {"available": False, "status": "Dominio no disponible"}
    if not os.path.exists(CC_INLINKS_DB):
        return {
            "available": False,
            "status": "No indexado: ejecute `python tools/build_cc_inlinks.py --targets <dominios.txt>` para construir la base de in-links reales.",
            "referrers": [],
        }
    try:
        conn = sqlite3.connect(CC_INLINKS_DB)
        conn.row_factory = sqlite3.Row
        candidates = _domain_candidates(clean_dom)
        rows = []
        # Exacto primero; luego ancestros (misma escalada que la Centralidad Armónica),
        # con atribución explícita si el match fue de un dominio ancestral.
        for cand in candidates:
            rows = conn.execute(
                """SELECT referrer_domain_norm, count, release_id
                   FROM cc_inlinks
                   WHERE target_domain_norm = ?
                   ORDER BY count DESC LIMIT ?""",
                (cand, limit),
            ).fetchall()
            if rows:
                conn.close()
                return {
                    "available": True,
                    "status": "In-links reales del Web Graph de Common Crawl",
                    "attribution": {
                        "level": "escalated" if cand != clean_dom else "exact",
                        "queried": clean_dom,
                        "matched": cand,
                    },
                    "referrers": [
                        {"domain": r["referrer_domain_norm"], "links": r["count"], "release": r["release_id"]}
                        for r in rows
                    ],
                }
        # Distinguir "calculado y sin enlaces" de "dominio fuera del lote calculado":
        # el segundo NO es un hecho sobre la revista, es un límite del índice local.
        computed = any(
            conn.execute(
                "SELECT 1 FROM cc_inlinks WHERE target_domain_norm = ? LIMIT 1", (c,)
            ).fetchone()
            for c in candidates
        )
        conn.close()
        if not computed:
            return {
                "available": False,
                "status": "Dominio fuera del lote calculado: sus in-links aún no se cuentan en el grafo local (no es que no tenga). Se incluye ejecutando tools/build_cc_inlinks.py con este dominio en --targets.",
                "referrers": [],
            }
        return {"available": True, "status": "Sin in-links registrados para el dominio (lote calculado, cero referidores).", "referrers": []}
    except Exception as e:
        log.warning("Error consultando %s: %s", CC_INLINKS_DB, e)
        return {"available": False, "status": f"Error consultando índice de in-links: {e}", "referrers": []}

