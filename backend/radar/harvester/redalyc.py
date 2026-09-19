"""Harvester Redalyc vía OAI-PMH institucional (UAEMex / Redalyc).

Endpoints funcionales verificados:
  Primary:  http://redalycojs.uaemex.mx/redalyc/oai
  Fallback: http://148.215.1.70/redalyc/oai

Verbos soportados:
  - Identify
  - ListIdentifiers
  - ListRecords (con soporte de set=ISSN y resumptionToken)
"""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET

from .. import config
from . import oai_dc
from .base import Article, SourceUnavailable

log = logging.getLogger("radar.redalyc")

OAI_ENDPOINTS = [
    "http://redalycojs.uaemex.mx/redalyc/oai",
    "http://148.215.1.70/redalyc/oai",
]
OAI_BASE = OAI_ENDPOINTS[0]

API_BASE = "https://api.redalyc.org"
_OAINS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}
_ISSN_RE = re.compile(r"^\d{4}-\d{3}[\dXx]$")


def test_availability(http) -> tuple[bool, str, str]:
    """Ping al OAI de Redalyc; prueba endpoint primario y fallback.
    Devuelve (disponible, detalle, endpoint_activo).
    """
    last_err = "sin respuesta"
    for endpoint in OAI_ENDPOINTS:
        try:
            r = http.get(endpoint, params={"verb": "Identify"}, timeout=15)
            if r.status_code == 200 and ("Identify" in r.text or "repositoryName" in r.text):
                return True, "OAI-PMH operativo", endpoint
            last_err = f"HTTP {r.status_code}: {r.text[:60]}"
        except Exception as e:
            last_err = f"error de conexión ({type(e).__name__})"
            continue
    return False, last_err, OAI_ENDPOINTS[0]


def parse_record(rec: ET.Element) -> Article | None:
    """Registro OAI de Redalyc -> `Article`.

    El parseo de los campos Dublin Core es **compartido** con el cosechador OJS
    (`oai_dc`): el vocabulario es el mismo y tener dos mapeos solo garantizaría que
    diverjan. Aquí queda únicamente lo específico de Redalyc: el identificador del
    header (`oai:redalyc.org:<id>`) y el ISSN del `setSpec`.
    """
    campos = oai_dc.dc_fields(rec)
    if not campos:
        return None

    articulo = oai_dc.article_from_fields(campos, source="redalyc", default_lang="es")
    if articulo is None:
        return None

    hdr = oai_dc.header_identifier(rec)
    m = re.search(r"oai:redalyc\.org:(\w+)", hdr or "")
    red_id = m.group(1) if m else None

    doi = articulo.doi
    articulo.url = (f"https://doi.org/{doi}" if doi
                    else (f"https://www.redalyc.org/articulo.oa?id={red_id}" if red_id else None))
    articulo.source_id = doi or (f"redalyc:{red_id}" if red_id else None)

    for spec in oai_dc.header_set_specs(rec):
        if _ISSN_RE.match(spec):
            articulo.issn = spec.upper()
            break
    return articulo


def harvest(http, date_from: str, max_articles: int = 300,
            resumption_token: str | None = None,
            sets: list[str] | None = None) -> list[Article]:
    """Cosecha registros de Redalyc vía OAI-PMH (con soporte de sets por revista)."""
    ok, detail, base_url = test_availability(http)
    if not ok:
        raise SourceUnavailable(f"Redalyc no disponible: {detail}")

    out: list[Article] = []

    # Si se especifican sets (ISSNs de revistas de comunicación), cosechar por set
    target_sets = [s for s in (sets or []) if s and _ISSN_RE.match(s.strip())]
    if target_sets:
        budget_per_set = max(10, max_articles // len(target_sets))
        for s_issn in target_sets:
            if len(out) >= max_articles:
                break
            try:
                params = {
                    "verb": "ListRecords",
                    "metadataPrefix": "oai_dc",
                    "set": s_issn.strip(),
                }
                r = http.get(base_url, params=params, timeout=30)
                if r.status_code != 200 or "<error code=" in r.text:
                    continue
                root = ET.fromstring(r.text)
                count_set = 0
                for rec in root.findall(".//oai:record", _OAINS):
                    art = parse_record(rec)
                    if art:
                        if not art.issn:
                            art.issn = s_issn.strip().upper()
                        out.append(art)
                        count_set += 1
                    if len(out) >= max_articles or count_set >= budget_per_set:
                        break
            except Exception as e:
                log.debug("Redalyc set %s: %s", s_issn, e)
                continue
            time.sleep(config.REQUEST_DELAY)
        return out

    # Cosecha general con resumptionToken
    token = resumption_token
    while len(out) < max_articles:
        params = {"verb": "ListRecords", "metadataPrefix": "oai_dc"}
        if token:
            params = {"verb": "ListRecords", "resumptionToken": token}
        else:
            params["from"] = f"{date_from}T00:00:00Z"
        try:
            r = http.get(base_url, params=params, timeout=45)
            r.raise_for_status()
        except Exception as e:
            log.warning("ListRecords falló: %s", e)
            break
        root = ET.fromstring(r.text)
        for rec in root.findall(".//oai:record", _OAINS):
            art = parse_record(rec)
            if art:
                out.append(art)
            if len(out) >= max_articles:
                break
        rt = root.find(".//oai:resumptionToken", _OAINS)
        token = rt.text.strip() if rt is not None and (rt.text or "").strip() else None
        if not token:
            break
        time.sleep(config.REQUEST_DELAY)
    return out