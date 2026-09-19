"""Pruebas unitarias para los modelos tipados de backend/radar/models.py."""
import pytest
from radar.models import (
    Article,
    Author,
    ChartingData,
    LibrarianAssistRequest,
    ReviewProtocol,
    ScreeningDecision,
)


def test_author_parsing():
    a1 = Author.from_any("Gipsy Gomez")
    assert a1.name == "Gipsy Gomez"

    a2 = Author.from_any({"family": "Gomez", "given": "Gipsy", "orcid": "0000-0001-2345-6789"})
    assert a2.family == "Gomez"
    assert a2.orcid == "0000-0001-2345-6789"


def test_article_from_dict():
    raw = {
        "title": "Un estudio sobre participación ciudadana",
        "doi": "10.1234/sts.2026",
        "abstract": "Resumen del estudio.",
        "authors": [{"family": "Pérez", "given": "Ana"}],
        "keywords": ["STS", "democratización"],
        "year": 2026,
        "source": "scielo",
        "access": "open",
    }
    art = Article(**raw)
    assert art.title == "Un estudio sobre participación ciudadana"
    assert art.year == 2026
    assert len(art.keywords) == 2

    d = art.to_dict()
    assert d["doi"] == "10.1234/sts.2026"
    assert "referenced_works" in d


def test_article_from_row_with_json_strings():
    row_dict = {
        "id": 42,
        "title": "Paper con JSON",
        "doi": "10.1000/1",
        "keywords": '["a", "b"]',
        "authors": '[{"family": "Lopez"}]',
        "referenced_ids": '["10.2000/2"]',
        "source": "openalex",
    }
    art = Article.from_row(row_dict)
    assert art.id == 42
    assert art.keywords == ["a", "b"]
    assert art.referenced_ids == ["10.2000/2"]
    assert art.authors == [{"family": "Lopez"}]


def test_review_protocol_validation():
    proto = ReviewProtocol(
        title="Revisión Sistemática UE-LATAM",
        research_question="¿Cómo estructuran los marcos de ciencia participativa?",
        framework="PCC",
        status="active",
    )
    assert proto.framework == "PCC"
    assert proto.status == "active"


def test_screening_decision_validation():
    dec = ScreeningDecision(
        protocol_id=1,
        doi="10.1000/test",
        decision="included",
        reason="Cumple criterios de inclusión",
    )
    assert dec.decision == "included"

    with pytest.raises(Exception):
        # Decisión inválida fuera de los Literals
        ScreeningDecision(
            protocol_id=1,
            doi="10.1000/test",
            decision="invalida_total",
        )


def test_charting_data_validation():
    chart = ChartingData(
        protocol_id=1,
        doi="10.1000/test",
        population="Profesionales de enfermería",
        concept="Liderazgo auténtico",
        context="Atención primaria en Chile",
        methodology="Estudio transversal",
        key_findings="Asociación negativa con burnout",
    )
    assert chart.concept == "Liderazgo auténtico"
    assert chart.protocol_id == 1


def test_librarian_assist_request():
    req = LibrarianAssistRequest(
        inquiry="ciencia participativa en latinoamerica",
        limit=20,
    )
    assert req.source == "live"
    assert req.limit == 20
