"""Pruebas unitarias para la Sonda Federada (OpenAIRE Graph v3, Dialnet Dismax y live_probe)."""
from unittest.mock import patch

from radar.harvester import dialnet, live_probe, openaire


def test_openaire_parse_item():
    sample_item = {
        "id": "openaire:12345",
        "mainTitle": "Citizen science policies in the European Union",
        "publicationDate": "2024-03-15",
        "authors": [
            {"fullName": "Elena Garcia", "name": "Elena", "surname": "Garcia", "pid": {"scheme": "orcid", "value": "0000-0002-1825-0097"}},
            {"fullName": "John Doe", "name": "John", "surname": "Doe", "pid": None}
        ],
        "pids": [
            {"scheme": "doi", "value": "10.1000/182"}
        ],
        "container": {
            "name": "Journal of European Science Policy",
            "issnOnline": "1234-5678",
            "vol": "12",
            "iss": "3"
        },
        "descriptions": ["<jats:p>An analysis of open governance frameworks in Europe.</jats:p>"],
        "subjects": [
            {"subject": {"value": "Citizen Science"}},
            {"subject": {"value": "Science Policy"}}
        ],
        "bestAccessRight": {"code": "OPEN"},
        "instances": [
            {"urls": ["https://doi.org/10.1000/182", "https://repo.eu/doc.pdf"]}
        ]
    }

    art = openaire.parse_item(sample_item)
    assert art is not None
    assert art.title == "Citizen science policies in the European Union"
    assert art.doi == "10.1000/182"
    assert art.year == 2024
    assert len(art.authors) == 2
    assert art.authors[0]["orcid"] == "0000-0002-1825-0097"
    assert art.journal_title == "Journal of European Science Policy"
    assert art.issn == "1234-5678"
    assert art.access == "open"
    assert art.pdf_url == "https://repo.eu/doc.pdf"
    assert "open governance" in (art.abstract or "").lower()


def test_dialnet_parse_html():
    sample_html = """
    <ul id="listadoDeArticulos">
        <li id="articulo998877" class="articulo impar">
            <div class="descripcion">
                <p class="titulo">
                    <span class="titulo"><a href="/servlet/articulo?codigo=998877">Marcos regulatorios de la ciencia ciudadana en España</a></span>
                </p>
                <p class="autores">
                    <a href="/servlet/autor?codigo=111">Carlos Pérez</a>
                    <a href="/servlet/autor?codigo=222">María Santos</a>
                </p>
                <p class="localizacion">
                    <span class="titulo"><a href="/servlet/revista?codigo=55">Revista Iberoamericana de Ciencia</a></span>, ISSN 0210-136X, 2023, págs. 45-60
                </p>
                <ul class="enlaces">
                    <li><a href="/descarga/articulo/998877.pdf">Texto completo</a></li>
                </ul>
            </div>
        </li>
    </ul>
    """
    articles = dialnet.parse_html(sample_html)
    assert len(articles) == 1
    art = articles[0]
    assert art.title == "Marcos regulatorios de la ciencia ciudadana en España"
    assert art.year == 2023
    assert len(art.authors) == 2
    assert art.authors[0]["family"] == "Pérez"
    assert art.issn == "0210-136X"
    assert art.access == "open"
    assert "dialnet.unirioja.es" in art.url


def test_dialnet_extract_article_details():
    sample_article_page = """
    <html>
        <body>
            <div id="resumen">
                <ul id="resumen">
                    <li xml:lang="es">
                        <p>español Con bases en observaciones y estudios del autor, el artículo aporta reflexiones acerca de la Responsabilidad Social Universitaria (RSU) desde una perspectiva organizacional.</p>
                    </li>
                </ul>
            </div>
            <div id="identificadores">
                <p>DOI: <a href="https://doi.org/10.18041/1900-3803/entramado.2.8843">10.18041/1900-3803/entramado.2.8843</a></p>
            </div>
        </body>
    </html>
    """
    det = dialnet.extract_article_details_from_html(sample_article_page)
    assert "abstract" in det
    assert "Responsabilidad Social Universitaria" in det["abstract"]
    assert not det["abstract"].startswith("español")  # Prefijo limpiado
    assert det.get("doi") == "10.18041/1900-3803/entramado.2.8843"


def test_live_probe_deduplication():
    # Simulamos que OpenAlex y OpenAIRE traen el mismo artículo con el mismo DOI
    mock_oa = [
        {
            "title": "Participatory sensing and civic engagement",
            "doi": "10.1016/j.envsci.2023.01",
            "year": 2023,
            "source_engine": "openalex",
            "authors": [{"given": "A", "family": "Smith"}],
            "keywords": ["sensing"]
        }
    ]
    mock_aire = [
        {
            "title": "Participatory sensing and civic engagement (EU edition)",
            "doi": "10.1016/j.envsci.2023.01", # Mismo DOI
            "year": 2023,
            "source_engine": "openaire",
            "authors": [{"given": "A", "family": "Smith"}],
            "keywords": ["policy"]
        },
        {
            "title": "Distinct European Paper on Governance",
            "doi": "10.1000/distinct.01",
            "year": 2024,
            "source_engine": "openaire",
            "authors": [{"given": "B", "family": "Mueller"}],
            "keywords": ["governance"]
        }
    ]
    mock_dial = [
        {
            "title": "Estudio sobre ciencia ciudadana",
            "doi": None,
            "year": 2022,
            "source_engine": "dialnet",
            "authors": [{"given": "C", "family": "Gómez"}],
            "keywords": ["monitoreo"]
        }
    ]

    with patch("radar.harvester.live_probe._probe_openalex", return_value=(mock_oa, 1)), \
         patch("radar.harvester.live_probe._probe_openaire", return_value=mock_aire), \
         patch("radar.harvester.live_probe._probe_dialnet", return_value=mock_dial):

        res = live_probe.probe_topic("ciencia ciudadana", federated=True)
        assert res is not None
        articles = res["articles"]
        # Debe haber 3 artículos en total (1 de OpenAlex, 1 único de OpenAIRE, 1 de Dialnet; el duplicado se descartó)
        assert len(articles) == 3
        dois = [a.get("doi") for a in articles if a.get("doi")]
        assert len(dois) == 2
        assert "10.1016/j.envsci.2023.01" in dois
        assert "10.1000/distinct.01" in dois

        # Fuentes registradas en el ecosistema
        sources = res["ecosystem"]["sources"]
        assert sources["openalex_live"] == 1
        assert sources["openaire_live"] == 1
        assert sources["dialnet_live"] == 1


def test_live_probe_resilience_when_source_fails():
    # Si OpenAIRE o Dialnet lanzan una excepción, OpenAlex debe mantenerse intacto
    mock_oa = [
        {
            "title": "Resilient Article",
            "doi": "10.1000/resilient",
            "year": 2024,
            "source_engine": "openalex",
            "authors": [{"given": "Test", "family": "Author"}],
            "keywords": ["resilience"]
        }
    ]

    def _failing_openaire(*args, **kwargs):
        raise ConnectionError("Network down")

    with patch("radar.harvester.live_probe._probe_openalex", return_value=(mock_oa, 1)), \
         patch("radar.harvester.live_probe._probe_openaire", side_effect=_failing_openaire), \
         patch("radar.harvester.live_probe._probe_dialnet", return_value=[]):

        res = live_probe.probe_topic("test resilience", federated=True)
        assert res is not None
        assert len(res["articles"]) == 1
        assert res["articles"][0]["title"] == "Resilient Article"
        assert res["ecosystem"]["sources"]["openalex_live"] == 1
        assert res["ecosystem"]["sources"]["openaire_live"] == 0
