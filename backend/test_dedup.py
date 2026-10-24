"""Pruebas de la deduplicación por título casi idéntico (fuzzy)."""
from unittest.mock import patch

from radar import dedup


def test_fusiona_titulos_casi_identicos():
    arts = [
        {"title": "Participación Ciudadana en las Políticas de Ciencia y Tecnología. Estudio Comparado",
         "doi": "10.1/a", "source": "openalex"},
        {"title": "Participación Ciudadana en las Política de Ciencia y Tecnología. Estudio Comparado",
         "doi": None, "source": "dialnet"},
    ]
    conservados, fusiones = dedup.deduplicar(arts, umbral=0.85)

    assert len(conservados) == 1
    assert len(fusiones) == 1
    assert "Participación" in fusiones[0]["conservado"]


def test_conserva_el_de_mayor_calidad():
    pobre = {"title": "Ciencia ciudadana y gobernanza tecnológica en América Latina",
             "doi": None, "abstract": "", "cited_by": 0, "source": "dialnet"}
    rico = {"title": "Ciencia ciudadana y gobernanza tecnológicas en América Latina",
            "doi": "10.1/x", "abstract": "texto", "cited_by": 12, "source": "openalex"}
    conservados, _ = dedup.deduplicar([pobre, rico], umbral=0.85)

    assert len(conservados) == 1
    assert conservados[0]["doi"] == "10.1/x", "debe conservar el registro con DOI y resumen"


def test_no_fusiona_titulos_distintos():
    arts = [
        {"title": "Ciencia ciudadana en Brasil", "doi": "10.1/a"},
        {"title": "El fútbol profesional y su economía", "doi": "10.1/b"},
    ]
    conservados, fusiones = dedup.deduplicar(arts)

    assert len(conservados) == 2
    assert fusiones == []


def test_no_fusiona_titulos_muy_cortos():
    # «Editorial» (1 palabra) no debe fusionarse por similitud difusa.
    arts = [{"title": "Editorial", "doi": "10.1/a"}, {"title": "Editorial", "doi": "10.1/b"}]
    conservados, _ = dedup.deduplicar(arts)

    assert len(conservados) == 2


def test_probe_topic_expone_duplicados_semanticos():
    from radar.harvester import live_probe

    # Títulos que el dedup EXACTO no junta (inflexión distinta) pero el fuzzy sí.
    mock = [
        {"title": "Marcos normativos de política científica en América Latina", "doi": "10.1/a",
         "year": 2024, "source_engine": "openalex", "authors": [], "keywords": []},
        {"title": "Marcos normativos de políticas científicas en América Latina", "doi": None,
         "year": 2023, "source_engine": "dialnet", "authors": [], "keywords": []},
    ]
    with patch("radar.harvester.live_probe._probe_openalex", return_value=(mock, 2)), \
         patch("radar.harvester.live_probe._probe_openaire", return_value=[]), \
         patch("radar.harvester.live_probe._probe_dialnet", return_value=[]):
        res = live_probe.probe_topic("marcos normativos ciencia ciudadana")

    assert "duplicados_semanticos" in res
    assert len(res["articles"]) == 1
    assert len(res["duplicados_semanticos"]) == 1
