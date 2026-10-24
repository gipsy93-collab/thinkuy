"""Pruebas del corpus curado para Escuelas de Pensamiento y Trayectoria (SPC).

Motivo (22-09-2026): con DOIs crudos de la búsqueda salen escuelas de paleontología o
bibliometría. Escuelas y SPC deben calcularse sobre los **incluidos** del protocolo.
"""
import sqlite3

from fastapi.testclient import TestClient
from radar import config, db
from radar.api import main as api_main


def _base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "grafo.db")
    conn = db.connect()
    db.init_db(conn)
    pid = db.save_protocol(conn, {"title": "P"})
    db.save_screening(conn, pid, doi="10.1/a", decision="included")
    db.save_screening(conn, pid, doi="10.1/b", decision="included")
    db.save_screening(conn, pid, doi="10.1/c", decision="excluded")
    conn.close()
    return pid


def _fake_live(capturado):
    def _fn(dois, **kwargs):
        capturado["dois"] = list(dois)
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        db.init_db(c)
        return c
    return _fn


def test_schools_usa_incluidos_del_protocolo(tmp_path, monkeypatch):
    pid = _base(tmp_path, monkeypatch)
    capturado: dict = {}
    monkeypatch.setattr("radar.api.routers.graph.citation_graph.build_live_graph",
                        _fake_live(capturado))
    res = TestClient(api_main.app).get(f"/api/graph/schools?protocol_id={pid}")

    assert res.status_code == 200
    datos = res.json()
    assert datos["origen_corpus"] == "protocolo"
    assert datos["corpus_n"] == 2
    assert set(capturado["dois"]) == {"10.1/a", "10.1/b"}  # solo los incluidos


def test_main_path_usa_incluidos_del_protocolo(tmp_path, monkeypatch):
    pid = _base(tmp_path, monkeypatch)
    capturado: dict = {}
    monkeypatch.setattr("radar.api.routers.graph.citation_graph.build_live_graph",
                        _fake_live(capturado))
    res = TestClient(api_main.app).get(f"/api/graph/main-path?protocol_id={pid}")

    assert res.status_code == 200
    assert res.json()["origen_corpus"] == "protocolo"
    assert set(capturado["dois"]) == {"10.1/a", "10.1/b"}


def test_sin_protocolo_ni_dois_es_global(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch)
    # Sin corpus, no se llama al grafo en vivo y se declara el origen global.
    res = TestClient(api_main.app).get("/api/graph/schools")
    assert res.status_code == 200
    assert res.json()["origen_corpus"] == "global"
