"""Cliente OAI-PMH genérico + parseo Dublin Core -> `Article`.

Existe para que **Redalyc y cualquier OJS compartan un solo parseo**. El vocabulario
`oai_dc` es el mismo en los dos (`dc:title`, `dc:creator`, `dc:date`, `dc:identifier`,
`dc:description` —el resumen—, `dc:subject` —palabras clave—, `dc:language`, `dc:source`),
de modo que duplicar el mapeo solo garantizaría que diverjan.

Verbos implementados: `Identify` y `ListRecords` con `resumptionToken`.

Uso:

    endpoint, intentos = detect_oai_endpoint("https://revista.edu/index.php/r", http)
    for registro in list_records(http, endpoint, set_spec="1234-5678", max_records=50):
        articulo = article_from_record(registro, source="ojs", base_url="https://revista.edu")
"""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Iterator

import httpx

from .. import config
from ..normalize import norm_lang, normalizar_espacios, unescape
from .base import Article

log = logging.getLogger("radar.oai_dc")

NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
ISSN_RE = re.compile(r"^\d{4}-\d{3}[\dXx]$")


class OAIError(RuntimeError):
    """El repositorio respondió con `<error>` OAI-PMH (p. ej. `noRecordsMatch`)."""

    def __init__(self, code: str, mensaje: str = ""):
        super().__init__(f"{code}: {mensaje}".strip(": "))
        self.code = code


def _texto(elemento: ET.Element | None) -> str:
    return unescape((elemento.text or "").strip()) if elemento is not None else ""


def _valores(meta: ET.Element, etiqueta: str) -> list[str]:
    """Todos los valores de una etiqueta Dublin Core, sin vacíos."""
    return [unescape((t.text or "").strip()) for t in meta.findall(f"dc:{etiqueta}", NS)
            if (t.text or "").strip()]


def error_de(raiz: ET.Element) -> OAIError | None:
    """Convierte un `<error>` OAI-PMH en excepción (si lo hay)."""
    error = raiz.find(".//oai:error", NS)
    if error is None:
        return None
    return OAIError(error.get("code", "sin_codigo"), re.sub(r"\s+", " ", _texto(error)))


def peticion(http: httpx.Client, endpoint: str, parametros: dict, timeout: float = 45.0) -> ET.Element:
    """Una petición OAI-PMH que devuelve el XML parseado, o lanza OAIError."""
    parametros = {k: v for k, v in parametros.items() if v not in (None, "")}
    respuesta = http.get(endpoint, params=parametros, timeout=timeout)
    if respuesta.status_code >= 400:
        raise OAIError(f"http_{respuesta.status_code}", respuesta.text[:120])
    try:
        raiz = ET.fromstring(respuesta.content)
    except ET.ParseError as e:
        raise OAIError("xml_invalido", str(e)) from e
    error = error_de(raiz)
    if error:
        raise error
    return raiz


def identify(http: httpx.Client, endpoint: str) -> dict:
    """`Identify`: nombre del repositorio y datos de contacto (sirve de sonda)."""
    raiz = peticion(http, endpoint, {"verb": "Identify"})
    identify_el = raiz.find(".//oai:Identify", NS)
    if identify_el is None:
        return {}
    gran = identify_el.findall(".//oai:granularity", NS)
    return {
        "repository_name": _texto(identify_el.find("oai:repositoryName", NS)),
        "base_url": _texto(identify_el.find("oai:baseURL", NS)),
        "earliest_datestamp": _texto(identify_el.find("oai:earliestDatestamp", NS)),
        "deleted_record": _texto(identify_el.find("oai:deletedRecord", NS)),
        "granularity": ",".join(_texto(g) for g in gran),
        "admin_email": _texto(identify_el.find("oai:adminEmail", NS)),
    }


def list_sets(http: httpx.Client, endpoint: str, max_sets: int = 200) -> list[dict]:
    """`ListSets`: en OJS cada set es una revista (o una sección dentro de ella)."""
    salida: list[dict] = []
    parametros = {"verb": "ListSets"}
    while len(salida) < max_sets:
        try:
            raiz = peticion(http, endpoint, parametros)
        except OAIError as e:
            if e.code == "noSetHierarchy":
                return salida
            raise
        for conjunto in raiz.findall(".//oai:set", NS):
            salida.append({"spec": _texto(conjunto.find("oai:setSpec", NS)),
                           "name": _texto(conjunto.find("oai:setName", NS))})
        token = raiz.find(".//oai:resumptionToken", NS)
        if token is None or not (token.text or "").strip():
            break
        parametros = {"verb": "ListSets", "resumptionToken": token.text.strip()}
    return salida[:max_sets]


def list_records(http: httpx.Client, endpoint: str, *, metadata_prefix: str = "oai_dc",
                 set_spec: str | None = None, date_from: str | None = None,
                 until: str | None = None, max_records: int = 200,
                 delay: float | None = None) -> Iterator[ET.Element]:
    """`ListRecords` paginado con `resumptionToken`. Devuelve registros OAI crudos."""
    delay = config.REQUEST_DELAY if delay is None else delay
    parametros: dict = {"verb": "ListRecords", "metadataPrefix": metadata_prefix}
    if set_spec:
        parametros["set"] = set_spec
    if date_from:
        parametros["from"] = date_from
    if until:
        parametros["until"] = until

    entregados = 0
    while True:
        try:
            raiz = peticion(http, endpoint, parametros)
        except OAIError as e:
            # `noRecordsMatch` es un final legítimo cuando el set/fecha no tiene registros.
            if e.code == "noRecordsMatch":
                return
            raise
        registros = raiz.findall(".//oai:record", NS)
        if not registros:
            return
        for registro in registros:
            yield registro
            entregados += 1
            if entregados >= max_records:
                return
        token = raiz.find(".//oai:resumptionToken", NS)
        if token is None or not (token.text or "").strip():
            return
        parametros = {"verb": "ListRecords", "resumptionToken": token.text.strip()}
        time.sleep(delay)


def dc_fields(registro: ET.Element) -> dict:
    """Campos Dublin Core de un registro OAI, o {} si no trae `oai_dc:dc`."""
    meta = registro.find(".//oai_dc:dc", NS)
    if meta is None:
        return {}
    return {
        "titles": _valores(meta, "title"),
        "creators": _valores(meta, "creator"),
        "contributors": _valores(meta, "contributor"),
        "dates": _valores(meta, "date"),
        "identifiers": _valores(meta, "identifier"),
        "descriptions": _valores(meta, "description"),
        "subjects": _valores(meta, "subject"),
        "languages": _valores(meta, "language"),
        "sources": _valores(meta, "source"),
        "types": _valores(meta, "type"),
        "publishers": _valores(meta, "publisher"),
        "relations": _valores(meta, "relation"),
        "rights": _valores(meta, "rights"),
        "formats": _valores(meta, "format"),
    }


def header_identifier(registro: ET.Element) -> str:
    return _texto(registro.find(".//oai:header/oai:identifier", NS))


def header_set_specs(registro: ET.Element) -> list[str]:
    return [_texto(s) for s in registro.findall(".//oai:header/oai:setSpec", NS) if _texto(s)]


def is_deleted(registro: ET.Element) -> bool:
    header = registro.find(".//oai:header", NS)
    return header is not None and (header.get("status") or "").lower() == "deleted"


def parse_authors(creators: list[str]) -> list[dict]:
    """`dc:creator` de OJS y Redalyc llega como 'Apellido, Nombre'."""
    autores = []
    for creador in creators:
        if "," in creador:
            familia, nombre = creador.split(",", 1)
            autores.append({"given": nombre.strip(), "family": familia.strip(), "orcid": None})
        else:
            autores.append({"given": creador.strip(), "family": "", "orcid": None})
    return autores


def doi_from_identifiers(identifiers: list[str]) -> str | None:
    for valor in identifiers:
        m = DOI_RE.search(valor)
        if m:
            return m.group(0).rstrip(".").lower()
    return None


def year_from_dates(dates: list[str]) -> tuple[int | None, str | None]:
    """Devuelve (año, fecha_publicacion) a partir de `dc:date`."""
    if not dates:
        return None, None
    m = re.match(r"(\d{4})", dates[0])
    if not m:
        return None, None
    anio = int(m.group(1))
    return anio, (dates[0][:10] if len(dates[0]) >= 10 else f"{anio}-01-01")


def language_of(fields: dict, identifiers: list[str] | None = None) -> str | None:
    """Idioma a partir de `dc:language` o del patrón `/es/`, `/pt/`, `/en/` de un identificador.

    Normaliza con `normalize.norm_lang`: `dc:language` llega como ISO 639-2 ('spa', 'por')
    y sin normalizar produciría 'sp' en lugar de 'es'.
    """
    for valor in (identifiers if identifiers is not None else fields.get("identifiers", [])):
        m = re.search(r"/(es|pt|en)/", valor)
        if m:
            return m.group(1)
    idiomas = fields.get("languages") or []
    for idioma in idiomas:
        normalizado = norm_lang(idioma)
        if normalizado:
            return normalizado
    return None


def article_from_fields(fields: dict, *, source: str, base_url: str | None = None,
                        source_id: str | None = None, default_lang: str = "es") -> Article | None:
    """Mapea campos Dublin Core a `Article`. Devuelve None si no hay título utilizable.

    Cuando hay varios `dc:description` (OJS publica uno por idioma y a veces añade notas
    editoriales) se toma **el más largo**: en el lote medido coincide siempre con el
    resumen real —los demás son traducciones recortadas o glosas de evaluación—.

    El texto pasa por `normalizar_espacios`, que **solo** colapsa espacios: se midió que
    reparar los pegotes del OAI de Redalyc por reglas modifica texto limpio (67,8 % con la
    regla de guion, 98 % con la de prefijos), de modo que para texto citable la vía es el
    PDF (escalón 4). Ver `normalize.py`.
    """
    titles = fields.get("titles") or []
    title = normalizar_espacios(titles[0]) if titles else ""
    if not title or len(title) < 8:
        return None

    identifiers = fields.get("identifiers") or []
    doi = doi_from_identifiers(identifiers)
    anio, pub_date = year_from_dates(fields.get("dates") or [])
    descriptions = [d for d in (fields.get("descriptions") or []) if d]
    sources = fields.get("sources") or []

    url = f"https://doi.org/{doi}" if doi else (identifiers[0] if identifiers else base_url)
    return Article(
        title=title,
        title_alt=normalizar_espacios(titles[1]) if len(titles) > 1 else None,
        abstract=normalizar_espacios(max(descriptions, key=len)) if descriptions else None,
        keywords=fields.get("subjects") or [],
        authors=parse_authors(fields.get("creators") or []),
        journal_title=sources[0] if sources else None,
        year=anio,
        pub_date=pub_date,
        lang=language_of(fields, identifiers) or default_lang,
        url=url,
        source=source,
        source_id=source_id or doi,
        doi=doi,
        access="oa",
    )


def article_from_record(registro: ET.Element, *, source: str, base_url: str | None = None,
                        default_lang: str = "es") -> Article | None:
    """Registro OAI completo -> `Article`. Usa el identificador del header como `source_id`."""
    if is_deleted(registro):
        return None
    fields = dc_fields(registro)
    if not fields:
        return None
    return article_from_fields(fields, source=source, base_url=base_url,
                               source_id=header_identifier(registro) or None,
                               default_lang=default_lang)
