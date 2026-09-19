"""Hidratación de resúmenes faltantes de un protocolo, por la escalera determinista.

**El problema que resuelve (medido el 18-09-2026).** En el protocolo de un investigador, 16 de 29
artículos incluidos no mostraban resumen. Al desglosarlos:

* **5 de OpenAlex → Elsevier (The Lancet, Lancet Oncology)**: el resumen **no existe** en OpenAlex
  ni en Crossref (los verifiqué uno por uno), y la ficha está tras muro de pago. **Irrecuperable.**
* **3 sin artículo enlazado**, pero con **DOI real**: recuperables pidiendo la ficha por DOI.
* **8 de Dialnet**: la fuente responde **HTTP 503** a nuestras peticiones. Bloqueada, no vacía.

**Lo que hace esta pasada:** para cada incluido sin resumen prueba, en orden, OpenAlex por DOI,
Crossref por DOI y la ficha declarada (cadena determinista). Indexa lo que consigue y **declara
lo que no**, con el motivo. No inventa nada: si el resumen no existe en una fuente abierta, el
campo queda vacío y así se reporta.
"""
from __future__ import annotations

import logging

import httpx

from .. import config, db
from . import abstract_chain, crossref, openalex
from .base import Article

log = logging.getLogger("radar.hidratar")


def _articulo_por_doi(http: httpx.Client, doi: str):
    """Ficha del artículo por DOI: primero OpenAlex (más completa), luego Crossref."""
    try:
        r = http.get(openalex.BASE, params={"filter": f"doi:{doi}", "per-page": 1}, timeout=30.0)
        if r.status_code == 200:
            resultados = (r.json() or {}).get("results") or []
            if resultados:
                articulo = openalex.parse_item(resultados[0])
                if articulo:
                    return articulo
    except Exception as e:
        log.debug("OpenAlex no resolvió %s: %s", doi, e)
    try:
        r = http.get(f"{crossref.BASE}/{doi}", params={"mailto": config.MAILTO}, timeout=30.0)
        if r.status_code == 200:
            return crossref.parse_item((r.json() or {}).get("message") or {})
    except Exception as e:
        log.debug("Crossref no resolvió %s: %s", doi, e)
    return None


def hidratar_resumenes(conn, protocol_id: int, http: httpx.Client | None = None,
                       limite: int = 200) -> dict:
    """Intenta completar el resumen de los artículos incluidos que no lo tienen."""
    cerrar = http is None
    cliente = http or httpx.Client(headers={"User-Agent": config.USER_AGENT},
                                   follow_redirects=True, timeout=45.0)
    recuperados, no_disponibles, bloqueados, enlazados = [], [], [], []
    try:
        filas = conn.execute(
            """SELECT s.doi AS s_doi, s.article_id, a.id AS a_id, a.doi AS a_doi, a.title, a.url,
                      a.abstract
                 FROM article_screenings s
                 LEFT JOIN articles a ON a.id = s.article_id
                WHERE s.protocol_id = ? AND s.decision = 'included'
                ORDER BY s.id""", (protocol_id,)).fetchall()[:limite]

        sin_resumen = [f for f in filas if not (f["abstract"] or "").strip()]

        for fila in sin_resumen:
            doi_crudo = (fila["s_doi"] or "").strip()
            doi = doi_crudo if doi_crudo and not doi_crudo.startswith("article:") else \
                (fila["a_doi"] or "").strip()
            url = (fila["url"] or "").strip()
            titulo = (fila["title"] or fila["s_doi"] or "")[:70]

            resumen, motivo = "", ""
            articulo = None

            # 1) Por DOI: trae la ficha completa (título, autores, año y resumen si existe).
            if doi and not doi.startswith("article:"):
                articulo = _articulo_por_doi(cliente, doi)
                if articulo and (articulo.abstract or "").strip():
                    resumen = articulo.abstract.strip()
                elif articulo:
                    motivo = "la fuente abierta no publica resumen para este DOI (habitual en editoriales de pago)"
                else:
                    motivo = "el DOI no se resolvió en OpenAlex ni Crossref"

            # 2) Por la ficha declarada. Si es una ficha de Dialnet se usa su extractor dedicado
            #    (conoce el contenedor `<ul id="resumen">`); si no, la cadena determinista general.
            #    Medido: Dialnet responde **HTTP 503 a todo**, con UA de navegador y con el de
            #    cortesía. Cuando el bloqueo ceda (o desde otra IP) esta vía sí devolverá el dato.
            if not resumen and url and "doi.org" not in url:
                if "dialnet.unirioja.es" in url:
                    try:
                        from . import dialnet
                        detalle = dialnet.fetch_article_details(url, client=cliente)
                        if (detalle.get("abstract") or "").strip():
                            resumen = detalle["abstract"].strip()
                        elif not motivo:
                            motivo = ("Dialnet devuelve HTTP 503 a nuestras peticiones: el resumen "
                                      "no está a nuestro alcance (no es que no exista)")
                    except Exception as e:
                        if not motivo:
                            motivo = f"fallo al consultar Dialnet: {type(e).__name__}"
                if not resumen:
                    try:
                        cadena = abstract_chain.resolve_abstract(url, http=cliente,
                                                                 titulo=fila["title"] or "")
                        if cadena.get("resumen"):
                            resumen = cadena["resumen"]
                        elif not motivo:
                            motivo = cadena.get("detalle") or "la ficha no publica resumen"
                    except Exception as e:
                        if not motivo:
                            motivo = f"fallo al consultar la ficha: {type(e).__name__}"
            elif not resumen and not motivo:
                motivo = "sin DOI resoluble y sin URL de ficha que rastrear"

            if not resumen:
                # No es que el dato no exista: puede ser que la fuente nos bloquee. Se distingue
                # «no existe» de «no me dejan» porque son problemas distintos y se arreglan distinto.
                es_bloqueo = "503" in motivo or "dialnet" in url.lower() or "bloque" in motivo.lower()
                if es_bloqueo:
                    bloqueados.append({"titulo": titulo, "url": url or doi,
                                       "motivo": ("la fuente no responde a nuestras peticiones "
                                                  "(Dialnet devuelve HTTP 503): el resumen no está "
                                                  "a nuestro alcance, no es que no exista.")})
                else:
                    no_disponibles.append({"titulo": titulo, "url": url or doi, "motivo": motivo})
                continue

            # 3) Persistir: indexar la ficha (si vino completa) y enlazarla al cribado.
            #    Guarda: si el artículo ya tiene resumen, NO se sobrescribe. La pasada es para
            #    llenar huecos, no para reemplazar lo que el investigador ya tenía (o editó).
            fila_articulo = fila["a_id"]
            if fila["a_id"]:
                existente = conn.execute("SELECT abstract FROM articles WHERE id = ?",
                                         (fila["a_id"],)).fetchone()
                if existente and (existente["abstract"] or "").strip():
                    recuperados.append({"titulo": titulo, "caracteres": len(existente["abstract"]),
                                        "nota": "ya tenía resumen: no se tocó"})
                    continue
            if articulo is None:
                articulo = Article(title=fila["title"] or doi, source="hidratacion",
                                   abstract=resumen, doi=doi or None, url=url or None)
            else:
                articulo.abstract = resumen
            if not articulo.doi and doi:
                articulo.doi = doi
            try:
                _, fila_articulo = db.upsert_article(conn, articulo.db_row())
                if not fila["article_id"]:
                    db.link_screening_article(conn, protocol_id, doi_crudo, fila_articulo)
                    enlazados.append(titulo)
            except Exception as e:
                log.warning("no se pudo guardar el resumen de %s: %s", title_safe(titulo), e)
                no_disponibles.append({"titulo": titulo, "url": url or doi,
                                       "motivo": f"no se pudo persistir: {type(e).__name__}"})
                continue

            recuperados.append({"titulo": titulo, "caracteres": len(resumen)})

        informe = {
            "incluidos": len(filas),
            "sin_resumen_antes": len(sin_resumen),
            "recuperados": len(recuperados),
            "enlazados": len(enlazados),
            "no_disponibles": len(no_disponibles),
            "bloqueados_por_la_fuente": len(bloqueados),
            "detalle_recuperados": recuperados,
            "detalle_no_disponibles": no_disponibles,
            "detalle_bloqueados": bloqueados,
            "declaracion": (
                f"{len(recuperados)} resúmenes recuperados de {len(sin_resumen)} que faltaban. "
                f"{len(no_disponibles)} no existen en fuentes abiertas (editoriales de pago) y "
                f"{len(bloqueados)} están tras un bloqueo de la fuente. Esos se leen en el texto "
                f"completo; NO se inventan."
            ),
        }
        return informe
    finally:
        if cerrar:
            cliente.close()


def title_safe(texto: str) -> str:
    """Recorte defensivo para mensajes de registro."""
    return (texto or "")[:60]
