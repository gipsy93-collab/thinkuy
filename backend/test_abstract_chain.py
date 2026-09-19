"""Pruebas de la cadena determinista del resumen (Hito 38).

Regla bajo prueba: el resumen sale de las meta etiquetas o del PDF declarado, NUNCA de
un modelo; y si no está, el campo queda vacío en lugar de inventarse.

Sin red: el cliente HTTP se inyecta y el PDF se sintetiza en memoria.
"""
import pymupdf as fitz
import pytest

from radar.harvester import abstract_chain


class RespuestaFalsa:
    def __init__(self, content: bytes = b"", status_code: int = 200, text: str = ""):
        self.content = content
        self.status_code = status_code
        self.text = text or content.decode("utf-8", "replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class ClienteFalso:
    """Devuelve las respuestas preparadas y registra las URLs pedidas."""

    def __init__(self, respuestas=None):
        self.respuestas = respuestas or {}
        self.llamadas = []

    def get(self, url, **kwargs):
        self.llamadas.append(url)
        return self.respuestas.get(url, RespuestaFalsa(status_code=404))

    def close(self):
        pass


class ClienteProhibido:
    """Falla si la cadena toca la red: debe resolverse en las meta etiquetas."""

    def get(self, *args, **kwargs):
        raise AssertionError("no debe haber llamada de red cuando citation_abstract existe")

    def close(self):
        pass


def pdf_con_resumen(texto: str) -> bytes:
    """PDF sintético de una página con encabezado 'Abstract' y su cuerpo."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 60), "Abstract", fontsize=14)
    y = 95
    for i in range(0, len(texto), 90):
        page.insert_text((50, y), texto[i:i + 90], fontsize=10)
        y += 14
    datos = doc.tobytes()
    doc.close()
    return datos


def pdf_sin_resumen(texto: str) -> bytes:
    """PDF cuya única sección es el cuerpo del artículo: sin encabezado de resumen.

    Es el caso real de las fichas de Redalyc (*Alteridad*, 2008-2011): el artículo
    existe, el resumen no.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 60), "Introduccion", fontsize=14)
    y = 95
    for i in range(0, len(texto), 90):
        page.insert_text((50, y), texto[i:i + 90], fontsize=10)
        y += 14
    datos = doc.tobytes()
    doc.close()
    return datos


RESUMEN_REAL = ("El presente estudio analiza la relación entre liderazgo auténtico y "
                "síndrome de burnout en profesionales de enfermería de atención primaria, "
                "con una muestra de 220 participantes y un diseño transversal.")
PDF_URL = "https://revista.ejemplo.org/articulo/123/pdf"


def html_con(abstract: str = "", pdf: str = "", description: str = "",
             titulo: str = "Un título cualquiera") -> str:
    partes = [f'<meta name="citation_title" content="{titulo}">']
    if abstract:
        partes.append(f'<meta name="citation_abstract" content="{abstract}">')
    if pdf:
        partes.append(f'<meta name="citation_pdf_url" content="{pdf}">')
    if description:
        partes.append(f'<meta property="og:description" content="{description}">')
    return "<html><head>" + "".join(partes) + "</head><body>cuerpo</body></html>"


# ── Vía 1: citation_abstract ────────────────────────────────────────────────

def test_citation_abstract_se_usa_sin_tocar_la_red():
    html = html_con(abstract=RESUMEN_REAL, pdf=PDF_URL)

    salida = abstract_chain.resolve_abstract(html, http=ClienteProhibido())

    assert salida["fuente"] == abstract_chain.FUENTE_META
    assert salida["resumen"] == RESUMEN_REAL
    assert salida["caracteres"] == len(RESUMEN_REAL)


def test_citation_abstract_corta_se_descarta():
    """Una etiqueta de 20 caracteres es plantilla, no resumen."""
    html = html_con(abstract="Ver más en la web")

    salida = abstract_chain.resolve_abstract(html, http=ClienteFalso())

    assert salida["fuente"] == abstract_chain.FUENTE_NINGUNA
    assert salida["resumen"] == ""


# ── Vía 2: citation_pdf_url -> PDF ──────────────────────────────────────────

def test_resumen_extraido_del_pdf_declarado():
    html = html_con(pdf=PDF_URL)
    cliente = ClienteFalso({PDF_URL: RespuestaFalsa(pdf_con_resumen(RESUMEN_REAL))})

    salida = abstract_chain.resolve_abstract(html, http=cliente)

    assert salida["fuente"] == abstract_chain.FUENTE_PDF
    assert salida["pdf_url"] == PDF_URL
    assert len(salida["resumen"]) >= abstract_chain.MIN_CARACTERES
    assert "liderazgo auténtico" in salida["resumen"]
    assert cliente.llamadas == [PDF_URL]


def test_pdf_sin_resumen_deja_el_campo_vacio():
    """Caso Redalyc/Alteridad: el PDF existe pero el artículo NO tiene resumen."""
    html = html_con(pdf=PDF_URL)
    cuerpo = ("Este artículo presenta una reflexión sobre la práctica docente y la "
              "gestión escolar en contextos rurales, sin resumen declarado por los autores.")
    cliente = ClienteFalso({PDF_URL: RespuestaFalsa(pdf_sin_resumen(cuerpo))})

    salida = abstract_chain.resolve_abstract(html, http=cliente)

    assert salida["resumen"] == ""
    assert salida["fuente"] == abstract_chain.FUENTE_NINGUNA
    assert "no contiene resumen" in salida["detalle"]


def test_pdf_que_no_es_pdf_no_rompe_la_cadena():
    html = html_con(pdf=PDF_URL)
    cliente = ClienteFalso({PDF_URL: RespuestaFalsa(b"<html>error 404</html>")})

    salida = abstract_chain.resolve_abstract(html, http=cliente)

    assert salida["resumen"] == ""
    assert salida["fuente"] == abstract_chain.FUENTE_NINGUNA


def test_error_http_del_pdf_se_reporta_sin_excepcion():
    html = html_con(pdf=PDF_URL)
    cliente = ClienteFalso({PDF_URL: RespuestaFalsa(b"", status_code=403)})

    salida = abstract_chain.resolve_abstract(html, http=cliente)

    assert salida["resumen"] == ""
    assert "403" in salida["detalle"]


def test_sin_pdf_ni_abstract_se_declara_el_motivo():
    salida = abstract_chain.resolve_abstract(html_con(), http=ClienteFalso())

    assert salida["fuente"] == abstract_chain.FUENTE_NINGUNA
    assert "sin citation_abstract" in salida["detalle"]


def test_allow_pdf_false_no_llama_a_la_red():
    html = html_con(pdf=PDF_URL)
    cliente = ClienteFalso({PDF_URL: RespuestaFalsa(pdf_con_resumen(RESUMEN_REAL))})

    salida = abstract_chain.resolve_abstract(html, http=cliente, allow_pdf=False)

    assert salida["resumen"] == ""
    assert cliente.llamadas == []


# ── Vía 3: description ──────────────────────────────────────────────────────

def test_description_larga_es_ultima_red():
    larga = ("Revista iberoamericana de comunicación científica. " + RESUMEN_REAL)
    salida = abstract_chain.resolve_abstract(html_con(description=larga), http=ClienteFalso())

    assert salida["fuente"] == abstract_chain.FUENTE_DESCRIPCION
    assert salida["resumen"].startswith("Revista iberoamericana")


def test_description_corta_o_eco_del_titulo_se_descarta():
    titulo = "Un título cualquiera"
    corta = abstract_chain.resolve_abstract(html_con(description="Revista de la facultad"),
                                            http=ClienteFalso())
    eco = abstract_chain.resolve_abstract(html_con(description=titulo * 6, titulo=titulo),
                                          http=ClienteFalso())

    assert corta["fuente"] == abstract_chain.FUENTE_NINGUNA
    assert eco["fuente"] == abstract_chain.FUENTE_NINGUNA


# ── Vía 2: DC.Description (OJS: un valor por idioma) ────────────────────────

def html_dublin(valores, idioma: str = "") -> str:
    """`valores` es una lista de (lang, texto); imita la salida de OJS."""
    partes = []
    if idioma:
        partes.append(f'<meta name="citation_language" content="{idioma}">')
    for lang, texto in valores:
        partes.append(f'<meta name="DC.Description" xml:lang="{lang}" content="{texto}">')
    return "<html><head>" + "".join(partes) + "</head><body>cuerpo</body></html>"


ES = "Esta revisión sistemática examina la relación entre la ecología de medios y la memoria colectiva."
EN = "This systematic review examines the relationship between media ecology and collective memory in the digital age today."
PT = "Nesta revisão sistemática, examina-se a relação entre a ecologia da mídia e a memória coletiva na era digital."


def test_dublin_core_es_el_resumen_cuando_no_hay_citation_abstract():
    salida = abstract_chain.resolve_abstract(html_dublin([("es", ES)]), http=ClienteProhibido())

    assert salida["fuente"] == abstract_chain.FUENTE_DUBLIN
    assert salida["resumen"] == ES


def test_dublin_core_elige_el_idioma_del_articulo():
    html = html_dublin([("en", EN), ("es", ES)], idioma="es")

    salida = abstract_chain.resolve_abstract(html, http=ClienteProhibido())

    assert salida["resumen"] == ES


def test_dublin_core_sin_idioma_declarado_toma_el_mas_largo():
    html = html_dublin([("en", EN), ("es", ES)])

    salida = abstract_chain.resolve_abstract(html, http=ClienteProhibido())

    assert len(salida["resumen"]) == max(len(EN), len(ES))


def test_dublin_core_ignora_valores_vacios_y_cortos():
    html = html_dublin([("es", ""), ("en", EN), ("pt", "Corto")], idioma="es")

    salida = abstract_chain.resolve_abstract(html, http=ClienteProhibido())

    assert salida["resumen"] == EN


def test_citation_abstract_tiene_prioridad_sobre_dublin_core():
    html = ("<html><head>"
            f'<meta name="citation_abstract" content="{RESUMEN_REAL}">'
            f'<meta name="DC.Description" xml:lang="es" content="{ES}">'
            "</head><body>cuerpo</body></html>")

    salida = abstract_chain.resolve_abstract(html, http=ClienteProhibido())

    assert salida["fuente"] == abstract_chain.FUENTE_META
    assert salida["resumen"] == RESUMEN_REAL


def test_idioma2_normaliza_codigos():
    assert abstract_chain.idioma2("spa") == "es"
    assert abstract_chain.idioma2("pt-BR") == "pt"
    assert abstract_chain.idioma2("es,en") == "es"
    assert abstract_chain.idioma2("") == ""


# ── Utilidades ──────────────────────────────────────────────────────────────

def test_limpiar_quita_la_etiqueta_inicial_y_normaliza():
    assert abstract_chain.limpiar("  ABSTRACT:  Texto  del   resumen. ") == "Texto del resumen."
    assert abstract_chain.limpiar("Resumen&nbsp;con entidades &amp; acentos") == \
        "Resumen con entidades & acentos"


def test_limpiar_no_mutila_texto_sin_separador():
    """Sin separador la etiqueta no se retira: 'Summary of the study' es contenido."""
    assert abstract_chain.limpiar("Summary of the study carried out in Chile") == \
        "Summary of the study carried out in Chile"


def test_pdf_url_con_respaldo_en_enlace_directo():
    html = '<a href="/descargas/articulo-42.pdf">PDF</a>'

    assert abstract_chain.pdf_url_from_html(html) == "/descargas/articulo-42.pdf"


def test_metas_acepta_name_y_property():
    etiquetas = abstract_chain.metas(html_con(abstract="x" * 100, description="y" * 200))

    assert etiquetas["citation_abstract"] == "x" * 100
    assert etiquetas["og:description"] == "y" * 200


def test_resolve_abstract_from_url_descarga_la_ficha():
    html = html_con(abstract=RESUMEN_REAL)
    cliente = ClienteFalso({"https://revista.ejemplo.org/articulo/123": RespuestaFalsa(text=html)})

    salida = abstract_chain.resolve_abstract_from_url("https://revista.ejemplo.org/articulo/123",
                                                      http=cliente)

    assert salida["fuente"] == abstract_chain.FUENTE_META
    assert len(cliente.llamadas) == 1


@pytest.mark.parametrize("campo", ["resumen", "fuente", "pdf_url", "caracteres", "detalle"])
def test_el_contrato_de_salida_es_estable(campo):
    salida = abstract_chain.resolve_abstract(html_con(), http=ClienteFalso())

    assert campo in salida


# ── Endpoint de la API ──────────────────────────────────────────────────────

def test_endpoint_resuelve_el_resumen_desde_el_html_entregado():
    """Sin `url` no hay descarga: se trabaja el HTML recibido (aquí, citation_abstract)."""
    from fastapi.testclient import TestClient

    from radar.api import main as api_main

    cliente = TestClient(api_main.app)
    respuesta = cliente.post("/api/metadata/abstract", json={"html": html_con(abstract=RESUMEN_REAL)})

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["status"] == "ok"
    assert datos["fuente"] == abstract_chain.FUENTE_META
    assert datos["resumen"] == RESUMEN_REAL


def test_endpoint_devuelve_sin_resumen_sin_inventar_nada():
    """Ficha sin resumen ni PDF consultable: campo vacío y motivo explícito."""
    from fastapi.testclient import TestClient

    from radar.api import main as api_main

    cliente = TestClient(api_main.app)
    respuesta = cliente.post("/api/metadata/abstract",
                             json={"html": html_con(pdf=PDF_URL), "allow_pdf": False})

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["status"] == "sin_resumen"
    assert datos["resumen"] == ""
    assert datos["fuente"] == abstract_chain.FUENTE_NINGUNA
    assert datos["pdf_url"] == PDF_URL


def test_endpoint_exige_url_o_html():
    from fastapi.testclient import TestClient

    from radar.api import main as api_main

    cliente = TestClient(api_main.app)
    respuesta = cliente.post("/api/metadata/abstract", json={})

    assert respuesta.status_code == 422
