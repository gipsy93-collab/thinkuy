"""Cadena determinista del resumen: meta etiquetas -> PDF. Sin modelo.

Por qué existe (Hito 38, §6): se midió que un SLM **rellena el resumen con texto
plausible cuando la fuente no lo contiene** — el 3B fabricó 6 resúmenes inexistentes
en fichas de Redalyc cuyos PDF tampoco los traen. Regla del proyecto: el resumen lo
localiza la capa determinista; **si la cadena entera no lo encuentra, el campo queda
vacío** y así se reporta. Ningún modelo lo rellena.

Orden de la cadena:

  1. ``citation_abstract``  — meta etiqueta de Google Scholar (SciELO la emite).
  2. ``DC.Description``     — Dublin Core; OJS publica ahí el resumen, un valor por idioma.
  3. ``citation_pdf_url``   — PDF declarado -> sección ``abstract`` (PyMuPDF).
  4. ``og:description`` / ``description`` — última red, con umbral alto para no
     ingerir reclamos de sitio.

Uso:

    with httpx.Client(headers={"User-Agent": config.USER_AGENT},
                      follow_redirects=True, timeout=45.0) as http:
        r = resolve_abstract(html_texto, http=http)
        # {"resumen": "...", "fuente": "pdf_abstract", "pdf_url": "...", ...}
"""
from __future__ import annotations

import html as _html
import logging
import re
import tempfile
from pathlib import Path

import httpx

from .. import config, text_extractor
from ..normalize import norm_lang

log = logging.getLogger("radar.abstract_chain")

# Umbrales. El estructural (60) descarta migas de pan y frases de plantilla, y deja pasar
# resúmenes cortos pero reales: el `DC.Description` más breve del lote medido tiene 78
# caracteres (Cuaderno 194, dspace.palermo.edu) y es lo que la revista declara como resumen.
# El de `description` (150) es más alto porque no es una etiqueta de resumen.
MIN_CARACTERES = 60
MIN_CARACTERES_DESCRIPCION = 150
MAX_BYTES_PDF = 25 * 1024 * 1024

FUENTE_META = "citation_abstract"
FUENTE_DUBLIN = "dc_description"
FUENTE_PDF = "pdf_abstract"
FUENTE_DESCRIPCION = "meta_description"
FUENTE_NINGUNA = "none"

# Solo se retira la etiqueta cuando va seguida de un separador ("Abstract: ..."); sin él,
# un resumen que empiece legítimamente por "Summary of the study" no pierde su primera palabra.
_ETIQUETA_INICIAL = re.compile(r"^\s*(?:abstract|resumen|resumo|summary)\s*[:\-–—]\s*", re.IGNORECASE)
_META_RE = re.compile(r"<meta\s+([^>]+?)>", re.IGNORECASE | re.DOTALL)
_ATRIBUTO_RE = re.compile(r'(?:name|property)\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_IDIOMA_RE = re.compile(r'(?:xml:)?lang\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_CONTENIDO_RE = re.compile(r'content\s*=\s*["\'](.*?)["\']', re.IGNORECASE | re.DOTALL)
_PDF_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', re.IGNORECASE)

# Códigos de tres letras que emiten las plataformas -> ISO de dos letras.
def idioma2(codigo: str | None) -> str:
    """Idioma a dos letras, delegando en `normalize.norm_lang` (una sola tabla en el proyecto).

    Acepta listas ('es,en' -> 'es'). Devuelve '' cuando no se puede normalizar.
    """
    return norm_lang((codigo or "").split(",")[0].strip()) or ""


def limpiar(texto: str | None) -> str:
    """Resuelve entidades, colapsa espacios y quita la etiqueta inicial ('Abstract:')."""
    t = re.sub(r"\s+", " ", _html.unescape(texto or "")).strip()
    return _ETIQUETA_INICIAL.sub("", t).strip()


def _meta_entradas(html_texto: str | None) -> list[dict]:
    """Todas las meta etiquetas como entradas con clave, valor y `lang` (si lo declaran)."""
    entradas: list[dict] = []
    for atributos in _META_RE.findall(html_texto or ""):
        atributo = _ATRIBUTO_RE.search(atributos)
        contenido = _CONTENIDO_RE.search(atributos)
        if not atributo or not contenido:
            continue
        idioma = _IDIOMA_RE.search(atributos)
        entradas.append({"clave": atributo.group(1).strip().lower(),
                         "valor": limpiar(contenido.group(1)),
                         "idioma": idioma2(idioma.group(1)) if idioma else ""})
    return entradas


def metas(html_texto: str | None) -> dict[str, str]:
    """meta etiquetas -> {clave: primer valor} (acepta `name` y `property`)."""
    salida: dict[str, str] = {}
    for entrada in _meta_entradas(html_texto):
        salida.setdefault(entrada["clave"], entrada["valor"])
    return salida


def abstract_from_meta(html_texto: str | None, titulo: str = "") -> tuple[str, str]:
    """Vías 1 y 4 de la cadena. Devuelve (texto, fuente)."""
    etiquetas = metas(html_texto)

    candidato = etiquetas.get("citation_abstract", "")
    if len(candidato) >= MIN_CARACTERES:
        return candidato, FUENTE_META

    titulo_norm = re.sub(r"\W+", " ", (titulo or "").lower()).strip()
    for clave in ("og:description", "description"):
        candidato = etiquetas.get(clave, "")
        if len(candidato) < MIN_CARACTERES_DESCRIPCION:
            continue
        # Un reclamo de sitio o un eco del título no es un resumen.
        if titulo_norm and re.sub(r"\W+", " ", candidato.lower()).strip() == titulo_norm:
            continue
        return candidato, FUENTE_DESCRIPCION

    return "", FUENTE_NINGUNA


def abstract_from_dublin_core(html_texto: str | None, idioma: str = "") -> tuple[str, str]:
    """Vía 2: `DC.Description` de OJS, que trae un valor por idioma.

    Selección determinista: primero el valor cuyo `lang` coincide con el idioma declarado
    del artículo; si no hay coincidencia, el valor no vacío más largo (el resumen completo
    frente a una traducción recortada, que en OJS es lo habitual).
    """
    valores = [e for e in _meta_entradas(html_texto)
               if e["clave"] in ("dc.description", "dcterms.abstract", "dcterms.description")
               and len(e["valor"]) >= MIN_CARACTERES]
    if not valores:
        return "", FUENTE_NINGUNA

    deseado = idioma2(idioma)
    if deseado:
        for entrada in valores:
            if entrada["idioma"] == deseado:
                return entrada["valor"], FUENTE_DUBLIN

    return max(valores, key=lambda e: len(e["valor"]))["valor"], FUENTE_DUBLIN


def pdf_url_from_html(html_texto: str | None) -> str:
    """URL del PDF declarada (`citation_pdf_url`), con respaldo en el primer enlace .pdf."""
    declarada = metas(html_texto).get("citation_pdf_url", "")
    if declarada:
        return declarada
    m = _PDF_HREF_RE.search(html_texto or "")
    return _html.unescape(m.group(1)) if m else ""


def abstract_from_pdf(pdf_bytes: bytes | None) -> str:
    """Vía 2 de la cadena: sección `abstract` de las primeras páginas del PDF."""
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        return ""
    if len(pdf_bytes) > MAX_BYTES_PDF:
        log.warning("PDF de %d bytes supera el máximo; se omite", len(pdf_bytes))
        return ""
    ruta: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            ruta = Path(tmp.name)
        extraido = text_extractor.extract_paper_to_markdown(ruta)
        if not extraido:
            return ""
        candidato = limpiar((extraido.get("sections") or {}).get("abstract") or "")
        return candidato if len(candidato) >= MIN_CARACTERES else ""
    except Exception as e:  # un PDF ilegible no debe tumbar la ingesta
        log.warning("extracción del PDF falló: %s", e)
        return ""
    finally:
        if ruta is not None:
            try:
                ruta.unlink(missing_ok=True)
            except OSError:
                pass


def resolve_abstract(html_texto: str | None, http: httpx.Client | None = None, *,
                     allow_pdf: bool = True, titulo: str = "", idioma: str = "") -> dict:
    """Ejecuta la cadena completa y devuelve el resultado con la fuente declarada.

    Nunca lanza por fallo de red: devuelve ``fuente="none"`` y el motivo en ``detalle``.
    """
    salida = {"resumen": "", "fuente": FUENTE_NINGUNA, "pdf_url": "", "caracteres": 0,
              "detalle": "sin resumen en meta etiquetas"}

    texto, fuente = abstract_from_meta(html_texto, titulo=titulo)
    if texto:
        salida.update(resumen=texto, fuente=fuente, caracteres=len(texto),
                      detalle=f"localizado en {fuente}")
        return salida

    texto, fuente = abstract_from_dublin_core(html_texto, idioma=idioma or metas(html_texto).get("citation_language", ""))
    if texto:
        salida.update(resumen=texto, fuente=fuente, caracteres=len(texto),
                      detalle=f"localizado en {fuente}")
        return salida

    pdf_url = pdf_url_from_html(html_texto)
    salida["pdf_url"] = pdf_url
    if not pdf_url:
        salida["detalle"] = "sin citation_abstract, sin DC.Description y sin citation_pdf_url"
        return salida
    if not allow_pdf:
        salida["detalle"] = f"PDF disponible pero no consultado ({pdf_url})"
        return salida

    cerrar = http is None
    cliente = http or httpx.Client(headers={"User-Agent": config.USER_AGENT},
                                   follow_redirects=True, timeout=45.0)
    try:
        respuesta = cliente.get(pdf_url)
        if respuesta.status_code >= 400:
            salida["detalle"] = f"PDF HTTP {respuesta.status_code}"
            return salida
        texto = abstract_from_pdf(respuesta.content)
    except Exception as e:
        salida["detalle"] = f"fallo al obtener el PDF: {type(e).__name__}"
        return salida
    finally:
        if cerrar:
            cliente.close()

    if texto:
        salida.update(resumen=texto, fuente=FUENTE_PDF, caracteres=len(texto),
                      detalle=f"localizado en la sección abstract del PDF ({pdf_url})")
    else:
        salida["detalle"] = f"el PDF no contiene resumen legible ({pdf_url})"
    return salida


def resolve_abstract_from_url(url: str, http: httpx.Client | None = None, **kwargs) -> dict:
    """Atajo: descarga la ficha y ejecuta la cadena sobre el HTML recibido."""
    cerrar = http is None
    cliente = http or httpx.Client(headers={"User-Agent": config.USER_AGENT},
                                   follow_redirects=True, timeout=45.0)
    try:
        respuesta = cliente.get(url)
        respuesta.raise_for_status()
        return resolve_abstract(respuesta.text, http=cliente, **kwargs)
    finally:
        if cerrar:
            cliente.close()
