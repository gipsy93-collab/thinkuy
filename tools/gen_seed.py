"""Genera la semilla de revistas de un campo desde OpenAlex `/sources`.

Uso:
  python tools/gen_seed.py --field ciencia_politica --search "political science" --country latam --output profiles/ciencia_politica_seed.json

Consulta OpenAlex /sources filtrando por búsqueda y (opcional) país/continente, y
escribe una lista de revistas compatible con el campo `seed_journals` del perfil.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

API = "https://api.openalex.org/sources"
TOPICS_API = "https://api.openalex.org/topics"
COUNTRY_FILTER = {
    "latam": "MX|AR|BR|CL|CO|PE|UY|VE|EC|BO|CR|PY|CU|DO|PA|GT|HN|NI|SV|PR",
    "iberoamerica": "MX|AR|BR|CL|CO|PE|UY|VE|EC|BO|CR|PY|CU|DO|PA|GT|HN|NI|SV|PR|ES|PT",
}

_MAILTO = {"mailto": "contacto@thinkuy.dev"}


def _resolve_topics(http: httpx.Client, search: str, limit: int = 6) -> list[str]:
    """Resuelve los IDs de topics de OpenAlex que mejor encajan con la búsqueda."""
    resp = http.get(TOPICS_API, params={"search": search, "per-page": limit, **_MAILTO}, timeout=45)
    resp.raise_for_status()
    return [t["id"].split("/")[-1] for t in (resp.json().get("results") or [])]


def _match_country(code: str | None, country: str | None) -> bool:
    if not country:
        return True
    allowed = COUNTRY_FILTER.get(country, country)
    return bool(code) and (code.upper() in allowed.split("|"))


def gen_seed(search: str, country: str | None = None, per_page: int = 200,
             min_works: int = 50) -> list[dict]:
    journals: dict[str, dict] = {}
    with httpx.Client(timeout=45, follow_redirects=True) as http:
        # 1) topics del campo -> 2) sources de esos topics
        topic_ids = _resolve_topics(http, search)
        params = {"per-page": min(per_page, 200), **_MAILTO}
        if topic_ids:
            params["filter"] = "topics.id:" + "|".join(topic_ids)
        cursor = "*"
        for _ in range(8):
            params["cursor"] = cursor
            resp = http.get(API, params=params)
            if resp.status_code != 200:
                break
            data = resp.json()
            for s in (data.get("results") or []):
                if (s.get("works_count") or 0) < min_works:
                    continue
                if not _match_country(s.get("country_code"), country):
                    continue
                issns = [i for i in (s.get("issn") or [])]
                if not issns:
                    continue
                journals[s["id"]] = {
                    "title": s.get("display_name"),
                    "issn_print": issns[0],
                    "issn_online": issns[1] if len(issns) > 1 else None,
                    "country": s.get("country_code"),
                    "works_count": s.get("works_count"),
                }
            cursor = data.get("meta", {}).get("next_cursor")
            if not cursor:
                break
            time.sleep(0.3)
    out = []
    for j in journals.values():
        out.append({"title": j["title"], "issn_print": j["issn_print"],
                    "issn_online": j["issn_online"], "country": j["country"]})
    out.sort(key=lambda x: x["title"].lower())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="gen-seed", description="Genera seed de revistas desde OpenAlex")
    ap.add_argument("--field", required=True)
    ap.add_argument("--search", required=True, help="Búsqueda temática en OpenAlex /sources")
    ap.add_argument("--country", default="iberoamerica", help="latam|iberoamerica|código ISO o vacío")
    ap.add_argument("--min-works", type=int, default=50)
    ap.add_argument("--output", default=None, help="Ruta del JSON de salida")
    args = ap.parse_args()

    seed = gen_seed(args.search, args.country, min_works=args.min_works)
    output = args.output or f"profiles/{args.field}_seed.json"
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(seed)} revistas -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())