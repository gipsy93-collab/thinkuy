"""Pruebas del endpoint POST /api/fulltext/backfill-auto.

Verifica la auto-ingesta coordinada de textos completos (Europe PMC XML + PDFs OA Unpaywall).
"""
import pytest
from fastapi.testclient import TestClient

from radar import config, db
from radar.api import main as api_main


@pytest.fixture()
def base_temporal(tmp_path, monkeypatch):
    """Base en archivo temporal aislada."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "prueba.db")
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    return tmp_path


def test_backfill_auto_vacio(base_temporal):
    client = TestClient(api_main.app)
    res = client.post("/api/fulltext/backfill-auto", json={"limit": 5})
    assert res.status_code == 200
    datos = res.json()
    assert datos["status"] == "ok"
    assert datos["total_evaluados"] == 0


def test_backfill_auto_con_protocolo_vacio(base_temporal):
    client = TestClient(api_main.app)
    conn = db.connect()
    pid = db.save_protocol(conn, {"title": "Test Protocol", "research_question": "test"})
    conn.close()

    res = client.post("/api/fulltext/backfill-auto", json={"protocol_id": pid, "limit": 5})
    assert res.status_code == 200
    datos = res.json()
    assert datos["status"] == "ok"
    assert datos["total_evaluados"] == 0


def test_backfill_auto_con_articulos_sin_oa(base_temporal, monkeypatch):
    from radar.harvester import fulltext_auto, unpaywall

    conn = db.connect()
    pid = db.save_protocol(conn, {"title": "Test Protocol", "research_question": "test"})
    art_id, _ = db.upsert_article(conn, {
        "title": "Articulo Cerrado",
        "doi": "10.1234/cerrado",
        "abstract": "Resumen",
        "source": "dialnet",
    })
    db.save_screening(conn, protocol_id=pid, doi="10.1234/cerrado", decision="included")
    conn.close()

    # Simular que PMC no lo tiene
    monkeypatch.setattr(fulltext_auto, "ingest_one", lambda conn, http, art: None)
    # Simular que Unpaywall indica que NO es OA
    monkeypatch.setattr(unpaywall, "enrich_doi", lambda http, doi: {"is_oa": False, "pdf_url": None})

    client = TestClient(api_main.app)
    res = client.post("/api/fulltext/backfill-auto", json={"protocol_id": pid, "limit": 5})
    assert res.status_code == 200
    datos = res.json()
    assert datos["status"] == "ok"
    assert datos["total_evaluados"] == 1
    assert datos["sin_oa"] == 1
    assert datos["recuperados_pmc"] == 0
    assert datos["recuperados_oa_pdf"] == 0


def test_backfill_auto_recupera_pmc(base_temporal, monkeypatch):
    from radar.harvester import fulltext_auto

    conn = db.connect()
    pid = db.save_protocol(conn, {"title": "Test Protocol", "research_question": "test"})
    art_id, _ = db.upsert_article(conn, {
        "title": "Articulo PMC",
        "doi": "10.1234/pmc_paper",
        "abstract": "Resumen",
        "source": "europepmc",
    })
    db.save_screening(conn, protocol_id=pid, doi="10.1234/pmc_paper", decision="included")
    conn.close()

    # Simular ingest_one exitoso
    monkeypatch.setattr(fulltext_auto, "ingest_one", lambda conn, http, art: {"doi": art["doi"], "full_text": True})

    client = TestClient(api_main.app)
    res = client.post("/api/fulltext/backfill-auto", json={"protocol_id": pid, "limit": 5})
    assert res.status_code == 200
    datos = res.json()
    assert datos["status"] == "ok"
    assert datos["total_evaluados"] == 1
    assert datos["recuperados_pmc"] == 1
    assert datos["recuperados_oa_pdf"] == 0

