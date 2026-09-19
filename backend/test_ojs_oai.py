"""Pruebas del cliente OAI-PMH y del micro-cosechador OJS `/oai`.

Sin red: el cliente HTTP se inyecta con XML OAI-PMH canónico.
"""

from radar.harvester import oai_dc, ojs_oai

CABECERA = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">')


class RespuestaFalsa:
    def __init__(self, texto: str, status_code: int = 200):
        self.status_code = status_code
        self.content = texto.encode("utf-8")
        self.text = texto


class ClienteFalsoOAI:
    """Responde según las `params` de la petición y registra lo pedido."""

    def __init__(self, respuestas: list[str] | str, por_defecto: str = ""):
        self.respuestas = [respuestas] if isinstance(respuestas, str) else list(respuestas)
        self.por_defecto = por_defecto
        self.llamadas: list[dict] = []

    def get(self, url, params=None, timeout=None, **kwargs):
        parametros = dict(params or {})
        self.llamadas.append({"url": url, **parametros})
        if self.respuestas:
            return RespuestaFalsa(self.respuestas.pop(0))
        return RespuestaFalsa(self.por_defecto, status_code=404)

    def close(self):
        pass


def xml_identify(nombre: str = "Revista de Prueba") -> str:
    return (CABECERA +
            '<Identify>'
            f'<repositoryName>{nombre}</repositoryName>'
            '<baseURL>https://revista.edu/index.php/r/oai</baseURL>'
            '<earliestDatestamp>2005-01-01</earliestDatestamp>'
            '<deletedRecord>no</deletedRecord>'
            '<granularity>YYYY-MM-DD</granularity>'
            '<adminEmail>editor@revista.edu</adminEmail>'
            '</Identify></OAI-PMH>')


def xml_error(codigo: str, mensaje: str = "no hay registros") -> str:
    return CABECERA + f'<error code="{codigo}">{mensaje}</error></OAI-PMH>'


def registro(indice: int, resumen: str = "", borrado: bool = False) -> str:
    estado = ' status="deleted"' if borrado else ""
    meta = "" if borrado else (
        '<metadata><oai_dc:dc '
        'xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:title>Ecología de medios y memoria colectiva en el sur global {indice}</dc:title>'
        f'<dc:creator>Pérez, Ana</dc:creator><dc:creator>Gómez, Luis</dc:creator>'
        f'<dc:date>202{indice}</dc:date>'
        f'<dc:identifier>https://doi.org/10.1234/abc.2024.{indice}</dc:identifier>'
        f'<dc:identifier>https://revista.edu/articulo/{indice}/es/</dc:identifier>'
        f'<dc:description>{resumen}</dc:description>'
        '<dc:subject>ecología de medios</dc:subject><dc:subject>memoria colectiva</dc:subject>'
        '<dc:language>spa</dc:language><dc:source>Revista de Prueba</dc:source>'
        '</oai_dc:dc></metadata>')
    return (f'<record><header{estado}>'
            f'<identifier>oai:revista.edu:articulo/{indice}</identifier>'
            f'<datestamp>2024-05-02</datestamp><setSpec>mirevista</setSpec>'
            f'</header>{meta}</record>')


def xml_list_records(registros: list[str], token: str | None = None) -> str:
    cuerpo = "".join(registros)
    cola = f"<resumptionToken>{token}</resumptionToken>" if token else \
           '<resumptionToken completeListSize="3" cursor="2"/>'
    return CABECERA + f"<ListRecords>{cuerpo}{cola}</ListRecords></OAI-PMH>"


RESUMEN = ("Esta revisión examina la relación entre la ecología de medios y la memoria "
           "colectiva en el sur global, con énfasis en la producción iberoamericana.")


# ── Endpoints candidatos y detección ────────────────────────────────────────

def test_candidatos_deriva_la_ruta_canonica_de_ojs3():
    candidatos = ojs_oai.candidatos("https://revista.edu/index.php/mirevista")

    assert candidatos[0] == "https://revista.edu/index.php/mirevista/oai"
    assert len(candidatos) == len(set(candidatos))


def test_candidatos_no_duplica_con_barra_final():
    assert ojs_oai.candidatos("https://revista.edu/index.php/mirevista/")[0] == \
        "https://revista.edu/index.php/mirevista/oai"


def test_deteccion_encuentra_el_endpoint_activo():
    cliente = ClienteFalsoOAI([xml_error("badArgument"), xml_identify("Revista de Prueba")])

    endpoint, intentos = ojs_oai.detect_oai_endpoint("https://revista.edu/index.php/r", cliente)

    assert endpoint == "https://revista.edu/oai"
    assert [i["ok"] for i in intentos] == [False, True]
    assert intentos[-1]["repositorio"] == "Revista de Prueba"


def test_deteccion_sin_endpoint_lo_declara():
    cliente = ClienteFalsoOAI([], por_defecto=xml_error("badVerb"))

    endpoint, intentos = ojs_oai.detect_oai_endpoint("https://revista.edu/index.php/r", cliente)

    assert endpoint is None
    assert intentos
    assert all(not i["ok"] for i in intentos)


class ClientePorURL:
    """Responde según la URL pedida: necesario cuando la ruta no se puede adivinar."""

    def __init__(self, respuestas: dict[str, tuple[int, str]]):
        self.respuestas = respuestas
        self.llamadas: list[str] = []

    def get(self, url, params=None, timeout=None, **kwargs):
        self.llamadas.append(url)
        status, texto = self.respuestas.get(url, (404, "<html>404</html>"))
        return RespuestaFalsa(texto, status_code=status)

    def close(self):
        pass


def test_deteccion_usa_el_enlace_declarado_en_la_pagina():
    """Instalación con prefijo no estándar: el endpoint solo aparece en la página."""
    landing = "https://revista.edu/index.php/r"
    cliente = ClientePorURL({
        landing: (200, '<html><a href="/index.php/otro/oai">OAI-PMH</a></html>'),
        "https://revista.edu/index.php/otro/oai": (200, xml_identify("Revista con prefijo raro")),
    })

    endpoint, intentos = ojs_oai.detect_oai_endpoint(landing, cliente)

    assert endpoint == "https://revista.edu/index.php/otro/oai"
    assert intentos[-1]["origen"] == "página"
    assert intentos[-1]["repositorio"] == "Revista con prefijo raro"


def test_descripcion_mas_larga_gana_cuando_hay_varias():
    """OJS publica un `dc:description` por idioma: se toma el resumen completo."""
    from xml.etree import ElementTree as ET

    corta = "Short abstract in English."
    larga = ("Resumen completo en español que describe el objetivo, el método, los "
             "resultados principales y las conclusiones del estudio con detalle suficiente.")
    xml = (CABECERA + '<ListRecords><record><header><identifier>oai:x:9</identifier></header>'
           '<metadata><oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" '
           'xmlns:dc="http://purl.org/dc/elements/1.1/">'
           '<dc:title>Un título suficientemente largo para pasar el filtro</dc:title>'
           f'<dc:description>{corta}</dc:description>'
           f'<dc:description>{larga}</dc:description>'
           '<dc:language>spa</dc:language></oai_dc:dc></metadata></record></ListRecords></OAI-PMH>')
    reg = ET.fromstring(xml).find(".//{http://www.openarchives.org/OAI/2.0/}record")

    articulo = oai_dc.article_from_record(reg, source="ojs")

    assert articulo.abstract == larga
    assert articulo.lang == "es"


# ── ListRecords con resumptionToken ─────────────────────────────────────────

def test_list_records_pagina_con_resumption_token():
    cliente = ClienteFalsoOAI([
        xml_list_records([registro(1), registro(2)], token="TOKEN-1"),
        xml_list_records([registro(3)]),
    ])

    registros = list(oai_dc.list_records(cliente, "https://revista.edu/oai", delay=0))

    assert len(registros) == 3
    assert cliente.llamadas[1]["resumptionToken"] == "TOKEN-1"
    # La segunda petición no debe reenviar metadataPrefix junto al token.
    assert "metadataPrefix" not in cliente.llamadas[1]


def test_list_records_respeta_max_records():
    cliente = ClienteFalsoOAI([xml_list_records([registro(1), registro(2)], token="T")])

    registros = list(oai_dc.list_records(cliente, "https://revista.edu/oai", max_records=1, delay=0))

    assert len(registros) == 1


def test_no_records_match_es_final_limpio_y_no_error():
    cliente = ClienteFalsoOAI([xml_error("noRecordsMatch")])

    assert list(oai_dc.list_records(cliente, "https://revista.edu/oai", delay=0)) == []


# ── Parseo Dublin Core -> Article ───────────────────────────────────────────

def test_article_from_record_mapea_los_campos_dc():
    from xml.etree import ElementTree as ET

    xml = CABECERA + f"<ListRecords>{registro(4, RESUMEN)}</ListRecords></OAI-PMH>"
    reg = ET.fromstring(xml).find(".//{http://www.openarchives.org/OAI/2.0/}record")

    articulo = oai_dc.article_from_record(reg, source="ojs",
                                          base_url="https://revista.edu/index.php/r")

    assert articulo.title.startswith("Ecología de medios")
    assert articulo.abstract == RESUMEN
    assert articulo.keywords == ["ecología de medios", "memoria colectiva"]
    assert articulo.authors[0] == {"given": "Ana", "family": "Pérez", "orcid": None}
    assert articulo.year == 2024
    assert articulo.doi == "10.1234/abc.2024.4"
    assert articulo.lang == "es"
    assert articulo.journal_title == "Revista de Prueba"
    assert articulo.source == "ojs"
    assert articulo.source_id == "oai:revista.edu:articulo/4"


def test_registro_borrado_se_omite():
    from xml.etree import ElementTree as ET

    xml = CABECERA + f"<ListRecords>{registro(5, borrado=True)}</ListRecords></OAI-PMH>"
    reg = ET.fromstring(xml).find(".//{http://www.openarchives.org/OAI/2.0/}record")

    assert oai_dc.article_from_record(reg, source="ojs") is None


def test_titulo_demasiado_corto_se_descarta():
    from xml.etree import ElementTree as ET

    xml = (CABECERA + '<ListRecords><record><header><identifier>oai:x:1</identifier></header>'
           '<metadata><oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" '
           'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Corto</dc:title>'
           '</oai_dc:dc></metadata></record></ListRecords></OAI-PMH>')
    reg = ET.fromstring(xml).find(".//{http://www.openarchives.org/OAI/2.0/}record")

    assert oai_dc.article_from_record(reg, source="ojs") is None


def test_helpers_de_identificadores():
    assert oai_dc.doi_from_identifiers(["https://doi.org/10.1234/ABC.1"]) == "10.1234/abc.1"
    assert oai_dc.doi_from_identifiers(["https://revista.edu/articulo/1"]) is None
    assert oai_dc.year_from_dates(["2023-07-15"]) == (2023, "2023-07-15")
    assert oai_dc.year_from_dates([]) == (None, None)


# ── Cosecha y huella editorial ──────────────────────────────────────────────

def test_harvest_journal_devuelve_articulos():
    cliente = ClienteFalsoOAI([xml_list_records([registro(1, RESUMEN), registro(2)])])

    articulos = ojs_oai.harvest_journal(cliente, "https://revista.edu/index.php/r/oai", delay=0)

    assert len(articulos) == 2
    assert all(a.source == "ojs" for a in articulos)


def test_journal_profile_resume_la_huella_editorial():
    cliente = ClienteFalsoOAI([xml_list_records([registro(1, RESUMEN), registro(2)])])
    articulos = ojs_oai.harvest_journal(cliente, "https://revista.edu/oai", delay=0)

    perfil = ojs_oai.journal_profile(articulos)

    assert perfil["total"] == 2
    assert perfil["anio_min"] == 2021 and perfil["anio_max"] == 2022
    assert perfil["idiomas"] == {"es": 2}
    assert perfil["cobertura"]["con_resumen"] == 1
    assert perfil["cobertura"]["con_resumen_pct"] == 50.0
    assert perfil["cobertura"]["con_doi"] == 2
    assert perfil["palabras_clave_frecuentes"]["memoria colectiva"] == 2
    assert perfil["revistas"] == {"Revista de Prueba": 2}


def test_journal_profile_sin_articulos():
    assert ojs_oai.journal_profile([])["total"] == 0


def test_harvest_from_url_detecta_cosecha_y_perfila():
    cliente = ClienteFalsoOAI([
        xml_identify(),
        xml_list_records([registro(1, RESUMEN)]),
        xml_identify(),
    ])

    resultado = ojs_oai.harvest_from_url("https://revista.edu/index.php/r", cliente, delay=0)

    assert resultado["endpoint"] == "https://revista.edu/index.php/r/oai"
    assert resultado["total"] == 1
    assert resultado["perfil"]["total"] == 1
    assert resultado["articulos"][0]["abstract"] == RESUMEN


def test_harvest_from_url_sin_endpoint_no_falla():
    cliente = ClienteFalsoOAI([], por_defecto=xml_error("badVerb"))

    resultado = ojs_oai.harvest_from_url("https://revista.edu/index.php/r", cliente)

    assert resultado["endpoint"] is None
    assert resultado["articulos"] == []
    assert "no se encontró" in resultado["detalle"]


# ── Compatibilidad con Redalyc (mismo vocabulario oai_dc) ───────────────────
# Protege la deduplicación: Redalyc y OJS deben compartir el parseo de campos DC
# y conservar cada uno sus identificadores propios.

def xml_redalyc() -> str:
    return (CABECERA +
            '<ListRecords><record><header>'
            '<identifier>oai:redalyc.org:467746250003</identifier>'
            '<datestamp>2010-01-01</datestamp>'
            '<setSpec>1390-325X</setSpec>'
            '</header><metadata>'
            '<oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:title>La tecno-comunicación: una moneda de tres lados</dc:title>'
            '<dc:creator>Zecchetto, Victorino</dc:creator>'
            '<dc:date>2008</dc:date>'
            '<dc:identifier>https://www.redalyc.org/articulo.oa?id=467746250003</dc:identifier>'
            '<dc:subject>comunicación</dc:subject>'
            '<dc:language>spa</dc:language>'
            '<dc:source>Alteridad. Revista de Educación</dc:source>'
            '</oai_dc:dc></metadata></record></ListRecords></OAI-PMH>')


def test_redalyc_parse_record_conserva_sus_identificadores_propios():
    from xml.etree import ElementTree as ET

    from radar.harvester import redalyc

    reg = ET.fromstring(xml_redalyc()).find(".//{http://www.openarchives.org/OAI/2.0/}record")

    articulo = redalyc.parse_record(reg)

    assert articulo.title == "La tecno-comunicación: una moneda de tres lados"
    assert articulo.source == "redalyc"
    assert articulo.source_id == "redalyc:467746250003"
    assert articulo.url == "https://www.redalyc.org/articulo.oa?id=467746250003"
    assert articulo.issn == "1390-325X"
    assert articulo.keywords == ["comunicación"]
    assert articulo.authors[0]["family"] == "Zecchetto"
    assert articulo.year == 2008
    assert articulo.lang == "es"
    assert articulo.journal_title == "Alteridad. Revista de Educación"
    assert articulo.abstract is None


def test_redalyc_y_ojs_extraen_el_mismo_resumen():
    """El vocabulario es el mismo: si hay `dc:description`, ambas fuentes lo ven."""
    from xml.etree import ElementTree as ET

    from radar.harvester import redalyc

    xml = xml_redalyc().replace(
        "<dc:subject>comunicación</dc:subject>",
        "<dc:description>Resumen declarado por la revista.</dc:description>"
        "<dc:subject>comunicación</dc:subject>")
    reg = ET.fromstring(xml).find(".//{http://www.openarchives.org/OAI/2.0/}record")

    assert redalyc.parse_record(reg).abstract == "Resumen declarado por la revista."
    assert oai_dc.article_from_record(reg, source="ojs").abstract == \
        "Resumen declarado por la revista."
