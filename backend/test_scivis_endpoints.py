"""Pruebas para los endpoints SCIVIS (/api/scivis/*)."""
import pytest
from fastapi.testclient import TestClient
from radar import config, db
from radar.api import main as api_main


@pytest.fixture()
def base_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "prueba.db")
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    return tmp_path


def test_scivis_ranking(base_temporal):
    client = TestClient(api_main.app)
    res = client.get("/api/scivis/ranking?limit=5")
    assert res.status_code == 200
    datos = res.json()
    assert "ranking" in datos
    assert isinstance(datos["ranking"], list)


def test_scivis_audit_valida_parametro(base_temporal):
    client = TestClient(api_main.app)
    res = client.get("/api/scivis/audit")
    assert res.status_code == 400
    assert "Debe proporcionar" in res.json()["detail"]


def test_scivis_in_out_links_valida_parametro(base_temporal):
    client = TestClient(api_main.app)
    res = client.get("/api/scivis/in-out-links")
    assert res.status_code == 400
    assert "Debe proporcionar" in res.json()["detail"]


def test_scivis_audit_con_revista_conocida(base_temporal):
    client = TestClient(api_main.app)
    res = client.get("/api/scivis/audit?q=comunicar")
    assert res.status_code == 200
    datos = res.json()
    assert datos["domain"] == "revistacomunicar.com"
    assert "harmonic_centrality" in datos
    assert "web_graph_analysis" in datos
    assert "in_out_audit" in datos
