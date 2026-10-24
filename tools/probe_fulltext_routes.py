"""Sonda de diagnóstico: ¿por qué no se recupera el texto completo?

Lee DOIs iberoamericanos del catálogo (SOLO LECTURA) y, para cada uno, prueba en orden las
rutas legales de acceso abierto, registrando **qué ruta funcionó** y **con qué status/contenido
fallaron las demás**. No descarga a disco ni escribe en la base: solo clasifica para decidir qué
ruta merece implementarse.

Rutas probadas (en orden de coste):
  1. `stored_pdf_url`      PDF ya guardado en el artículo (Unpaywall lo dejó, nadie lo bajó).
  2. `unpaywall_pdf`       Unpaywall `best_oa_location.url_for_pdf` por DOI.
  3. `openaire_instance`   OpenAIRE Graph: URLs de instancia que apuntan a PDF.
  4. `landing_citation`    Página del artículo -> `citation_pdf_url` / primer enlace .pdf.
  5. `scielo_pattern`      Patrón de PDF de SciELO derivado de la URL de la ficha.

Reglas: solo OA, `robots.txt` consultado por dominio, UA cortés y pausa entre peticiones.

Uso:
  python tools/probe_fulltext_routes.py --db data/radar.db --limit 30 \
      --out data/demo/probe_fulltext_routes.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.robotparser as robotparser
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from radar import config  # noqa: E402

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
UNPAYWALL_API = "https://api.unpaywall.org/v2"
OPENAIRE_API = "https://api.openaire.eu/graph/v3/research-products"


# ────────────────────────────────────────────────────────────── robots.txt
_ROBOTS: dict[str, robotparser.RobotFileParser | None] = {}


def robots_allows(client: httpx.Client, url: str, ua: str = BROWSER_UA) -> bool:
    """¿Permite robots.txt esta URL para nuestro UA? (por dominio, cacheado)."""
    try:
        parts = httpx.URL(url)
        base = f"{parts.scheme}://{parts.host}"
        if base not in _ROBOTS:
            rp = robotparser.RobotFileParser()
            try:
                resp = client.get(f"{base}/robots.txt", timeout=15)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    rp = None  # sin robots -> permitido
            except Exception:
                rp = None
            _ROBOTS[base] = rp
        rp = _ROBOTS[base]
        return True if rp is None else rp.can_fetch(ua, url)
    except Exception:
        return True


# ────────────────────────────────────────────────────────────── utilidades
def _looks_like_pdf(resp: httpx.Response) -> bool:
    if resp is None:
        return False
    ct = (resp.headers.get("content-type") or "").lower()
    head = resp.content[:5]
    return head[:4] == b"%PDF" or "application/pdf" in ct


def _meta_citation_pdf(html: str) -> str | None:
    m = re.search(
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r'<meta[^>]+content=["\']([^"\']+\.pdf)["\'][^>]+name=["\']citation_pdf_url["\']',
            html, re.IGNORECASE,
        )
    return unescape(m.group(1).strip()) if m else None


def _first_pdf_link(html: str) -> str | None:
    for m in re.finditer(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html, re.IGNORECASE):
        href = unescape(m.group(1))
        if any(k in href.lower() for k in ("pdf", "/download", "descarga")):
            return href
    return None


_NO_TEXT_RE = re.compile(
    r"(no es posible acceder|no se puede acceder|n[aã]o [eé] poss[ií]vel (acessar|acceder)|"
    r"texto completo n[aã]o dispon|full text is not available|conte[uú]do n[aã]o dispon|"
    r"texto completo.{0,20}remov)",
    re.IGNORECASE,
)
_WAF_RE = re.compile(
    r"(establishing a secure connection|checking your browser|cf-browser|"
    r"attention required|just a moment|access denied)",
    re.IGNORECASE,
)


def _scielo_pdf_candidates(url: str, lang: str | None) -> list[str]:
    """Candidatos de PDF a partir de la URL de la ficha de SciELO."""
    cands: list[str] = []
    m = re.search(r"(https?://[^/]+)/j/([^/]+)/a/([^/?#]+)/?", url)
    if m:
        base, journal, pid = m.group(1), m.group(2), m.group(3)
        for lg in [lang, "es", "en", "pt"]:
            if lg:
                cands.append(f"{base}/j/{journal}/a/{pid}/?format=pdf&lang={lg}")
        cands.append(f"{base}/j/{journal}/a/{pid}/?format=pdf")
    m2 = re.search(r"[?&]pid=([^&#]+)", url)
    if m2:
        pid = m2.group(1)
        cands.append(f"https://www.scielo.br/scielo.php?script=sci_pdf&pid={pid}")
        cands.append(f"https://www.scielo.br/pdf/{pid[:9]}/n{pid[-4:]}.pdf")
    return list(dict.fromkeys(cands))


# ────────────────────────────────────────────────────────────── rutas
def try_fetch(client: httpx.Client, url: str, ua: str) -> dict:
    """GET una URL y clasifica el resultado. Respeta robots.txt."""
    url = unescape(url)
    if not robots_allows(client, url, ua):
        return {"ok": False, "motivo": "robots_disallow", "url": url}
    try:
        resp = client.get(url, headers={"User-Agent": ua, "Accept": "application/pdf,text/html,*/*"},
                          timeout=30, follow_redirects=True)
    except Exception as e:
        return {"ok": False, "motivo": f"error:{type(e).__name__}", "url": url}
    es_pdf = _looks_like_pdf(resp)
    return {
        "ok": es_pdf,
        "motivo": "pdf" if es_pdf else "no_pdf",
        "status": resp.status_code,
        "content_type": (resp.headers.get("content-type") or "")[:60],
        "bytes": len(resp.content),
        "url": str(resp.url),
    }


def route_stored_pdf(client, art, ua, email=None) -> dict | None:
    url = (art.get("pdf_url") or "").strip()
    if not url:
        return None
    return {"ruta": "stored_pdf_url", **try_fetch(client, url, ua)}


def route_unpaywall(client, art, ua, email=None) -> dict | None:
    doi = (art.get("doi") or "").strip().lower()
    if not doi:
        return None
    try:
        r = client.get(f"{UNPAYWALL_API}/{doi}", params={"email": email or config.MAILTO}, timeout=30)
        if r.status_code != 200:
            return {"ruta": "unpaywall_pdf", "ok": False, "motivo": f"http_{r.status_code}"}
        best = r.json().get("best_oa_location") or {}
        pdf = best.get("url_for_pdf") or best.get("url")
        if not pdf:
            return {"ruta": "unpaywall_pdf", "ok": False, "motivo": "sin_oa"}
        return {"ruta": "unpaywall_pdf", **try_fetch(client, pdf, ua)}
    except Exception as e:
        return {"ruta": "unpaywall_pdf", "ok": False, "motivo": f"error:{type(e).__name__}"}


def route_openaire(client, art, ua, email=None) -> dict | None:
    doi = (art.get("doi") or "").strip().lower()
    if not doi:
        return None
    try:
        r = client.get(OPENAIRE_API, params={"search": doi, "pageSize": 3}, timeout=30)
        if r.status_code != 200:
            return {"ruta": "openaire_instance", "ok": False, "motivo": f"http_{r.status_code}"}
        for item in r.json().get("results") or []:
            for inst in item.get("instances") or []:
                for u in inst.get("urls") or []:
                    if str(u).lower().endswith(".pdf") or "pdf" in str(u).lower():
                        return {"ruta": "openaire_instance", **try_fetch(client, str(u), ua)}
        return {"ruta": "openaire_instance", "ok": False, "motivo": "sin_pdf"}
    except Exception as e:
        return {"ruta": "openaire_instance", "ok": False, "motivo": f"error:{type(e).__name__}"}


def route_doi_citation(client, art, ua, email=None) -> dict | None:
    """Resuelve el DOI y extrae `citation_pdf_url` de la ficha viva del editor.

    Es la ruta que faltaba: la página de SciELO responde 200 con un UA de navegador y declara
    el PDF real en `citation_pdf_url`. Si la ficha dice que no hay texto completo, se declara.
    """
    doi = (art.get("doi") or "").strip().lower()
    if not doi:
        return None
    doi_url = f"https://doi.org/{doi}"
    if not robots_allows(client, doi_url, ua):
        return {"ruta": "doi_citation_pdf", "ok": False, "motivo": "robots_disallow"}
    try:
        resp = client.get(doi_url, headers={"User-Agent": ua}, timeout=30, follow_redirects=True)
    except Exception as e:
        return {"ruta": "doi_citation_pdf", "ok": False, "motivo": f"error:{type(e).__name__}"}
    if resp.status_code != 200:
        return {"ruta": "doi_citation_pdf", "ok": False, "motivo": f"http_{resp.status_code}"}
    html = resp.text
    if _WAF_RE.search(html):
        return {"ruta": "doi_citation_pdf", "ok": False, "motivo": "waf",
                "final_url": str(resp.url)[:150]}
    pdf = _meta_citation_pdf(html) or _first_pdf_link(html)
    if not pdf:
        motivo = "declarado_sin_texto" if _NO_TEXT_RE.search(html) else "sin_citation_pdf"
        return {"ruta": "doi_citation_pdf", "ok": False, "motivo": motivo,
                "final_url": str(resp.url)[:150]}
    if pdf.startswith("/"):
        u = httpx.URL(str(resp.url))
        pdf = f"{u.scheme}://{u.host}{pdf}"
    return {"ruta": "doi_citation_pdf", **try_fetch(client, pdf, ua)}


def route_landing(client, art, ua, email=None) -> dict | None:
    url = (art.get("url") or "").strip()
    if not url:
        return None
    if not robots_allows(client, url, ua):
        return {"ruta": "landing_citation", "ok": False, "motivo": "robots_disallow", "url": url}
    try:
        resp = client.get(url, headers={"User-Agent": ua}, timeout=30, follow_redirects=True)
    except Exception as e:
        return {"ruta": "landing_citation", "ok": False, "motivo": f"error:{type(e).__name__}"}
    if resp.status_code != 200:
        return {"ruta": "landing_citation", "ok": False, "motivo": f"http_{resp.status_code}", "url": url}
    html = resp.text
    pdf = _meta_citation_pdf(html) or _first_pdf_link(html)
    if not pdf:
        tiene_cuerpo = bool(re.search(r'(articleBody|sci_arttext|/html/)', html, re.IGNORECASE))
        return {"ruta": "landing_citation", "ok": False,
                "motivo": "cuerpo_html" if tiene_cuerpo else "sin_pdf_en_ficha",
                "bytes": len(resp.content), "url": str(resp.url)}
    if pdf.startswith("/"):
        pdf = f"{httpx.URL(str(resp.url)).scheme}://{httpx.URL(str(resp.url)).host}{pdf}"
    return {"ruta": "landing_citation", **try_fetch(client, pdf, ua)}


def route_scielo(client, art, ua, email=None) -> dict | None:
    url = (art.get("url") or "").strip()
    if "scielo" not in url.lower():
        return None
    cands = _scielo_pdf_candidates(url, art.get("lang"))
    for c in cands:
        res = try_fetch(client, c, ua)
        if res.get("ok"):
            return {"ruta": "scielo_pattern", **res}
    return {"ruta": "scielo_pattern", "ok": False,
            "motivo": "ningun_candidato", "candidatos": len(cands)}


ROUTES = [route_stored_pdf, route_unpaywall, route_doi_citation, route_openaire, route_landing, route_scielo]


# ────────────────────────────────────────────────────────────── selección
def load_articles(db_path: str, limit: int, sources: list[str], random_sample: bool = False) -> list[dict]:
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(sources))
    orden = "RANDOM()" if random_sample else \
        "CASE WHEN pdf_url IS NOT NULL AND pdf_url != '' THEN 0 ELSE 1 END, COALESCE(cited_by, 0) DESC"
    rows = conn.execute(
        f"""SELECT doi, title, source, url, pdf_url, lang, year FROM articles
            WHERE doi IS NOT NULL AND doi != ''
              AND (source IN ({placeholders}) OR doi LIKE '10.1590/%')
            ORDER BY {orden}
            LIMIT ?""",
        [*sources, limit],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description="Sonda de rutas de texto completo (solo lectura).")
    ap.add_argument("--db", default="data/radar.db")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--sources", default="scielo,redalyc,dialnet")
    ap.add_argument("--delay", type=float, default=0.6)
    ap.add_argument("--random", action="store_true", help="Muestreo aleatorio (estimación sin sesgo)")
    ap.add_argument("--out", default="data/demo/probe_fulltext_routes.json")
    args = ap.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    articles = load_articles(args.db, args.limit, sources, random_sample=args.random)
    print(f"Artículos a sondear: {len(articles)} (fuentes: {sources})")

    email = config.MAILTO
    resultados = []
    with httpx.Client(headers={"User-Agent": BROWSER_UA}) as client:
        for i, art in enumerate(articles, 1):
            doi = (art.get("doi") or "").strip().lower()
            fila = {"doi": doi, "title": (art.get("title") or "")[:90],
                    "source": art.get("source"), "rutas": []}
            ganadora = None
            for route in ROUTES:
                res = route(client, art, BROWSER_UA, email)
                if res is None:
                    continue
                fila["rutas"].append(res)
                if res.get("ok"):
                    ganadora = res["ruta"]
                    break
                time.sleep(args.delay)
            fila["ganadora"] = ganadora
            resultados.append(fila)
            estado = f"OK  {ganadora}" if ganadora else "SIN RUTA"
            print(f"[{i}/{len(articles)}] {estado:22s} {doi}")

    # Resumen por ruta
    resumen: dict[str, dict] = {}
    for fila in resultados:
        for r in fila["rutas"]:
            d = resumen.setdefault(r["ruta"], {"intentos": 0, "ok": 0, "motivos": {}})
            d["intentos"] += 1
            if r.get("ok"):
                d["ok"] += 1
            else:
                m = r.get("motivo", "?")
                d["motivos"][m] = d["motivos"].get(m, 0) + 1

    con_texto = sum(1 for f in resultados if f["ganadora"])
    salida = {
        "generado": datetime.now(timezone.utc).isoformat(),
        "db": args.db,
        "total": len(resultados),
        "con_texto_completo": con_texto,
        "cobertura": round(100 * con_texto / len(resultados), 1) if resultados else 0.0,
        "resumen_por_ruta": resumen,
        "resultados": resultados,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n-- Resumen por ruta --")
    for ruta, d in sorted(resumen.items(), key=lambda x: -x[1]["ok"]):
        print(f"{ruta:18s} ok {d['ok']:2d}/{d['intentos']:2d}  motivos: {d['motivos']}")
    print(f"\nCobertura: {salida['cobertura']}% ({con_texto}/{len(resultados)})")
    print(f"Informe: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
