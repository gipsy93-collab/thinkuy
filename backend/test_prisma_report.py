"""Pruebas de la lista de verificación PRISMA 2020 y del informe final exportable.

Guía: Page MJ et al., «Declaración PRISMA 2020», Rev Esp Cardiol. 2021;74(9):790-799.
La lista tiene 27 ítems numerados; con subítems son 42 filas.
"""
import sqlite3

from fastapi.testclient import TestClient
from radar import config, db, prisma_report
from radar.api import main as api_main


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


def test_checklist_tiene_los_27_items_con_subitems():
    conn = _conn()
    pid = db.save_protocol(conn, {"title": "P", "research_question": "¿cómo se gobierna?"})

    cl = prisma_report.build_checklist(conn, pid)
    ids = [i["id"] for i in cl["items"]]

    assert "1" in ids and "27" in ids and "16a" in ids and "20d" in ids
    assert cl["total"] == 42, "27 ítems numerados -> 42 filas con subítems"
    item4 = next(i for i in cl["items"] if i["id"] == "4")
    assert item4["estado"] == "auto"
    assert "¿cómo se gobierna?" in str(item4["evidencia"])


def test_checklist_rellena_fuentes_y_flujo():
    conn = _conn()
    pid = db.save_protocol(conn, {"title": "P"})
    db.log_protocol_search(conn, pid, "openalex", 10, query="x", year_from=2005, year_to=2025)
    db.save_screening(conn, pid, doi="10.1/a", decision="included")

    cl = prisma_report.build_checklist(conn, pid)

    item6 = next(i for i in cl["items"] if i["id"] == "6")
    assert item6["estado"] == "auto"
    assert item6["evidencia"]["openalex"]["registros"] == 10
    item16 = next(i for i in cl["items"] if i["id"] == "16a")
    assert item16["evidencia"]["identificados"] == 10
    assert item16["evidencia"]["incluidos"] == 1


def test_checklist_declara_lo_manual_sin_inventarlo():
    conn = _conn()
    pid = db.save_protocol(conn, {"title": "P"})

    cl = prisma_report.build_checklist(conn, pid)

    item23 = next(i for i in cl["items"] if i["id"] == "23a")
    assert item23["estado"] == "manual"
    assert item23["evidencia"] is None
    # El registro no está implementado: se declara, no se inventa.
    item24a = next(i for i in cl["items"] if i["id"] == "24a")
    assert item24a["estado"] == "declarado"


def test_reporte_markdown_contiene_secciones_y_limitaciones():
    conn = _conn()
    pid = db.save_protocol(conn, {"title": "Revisión X", "research_question": "¿q?"})
    db.log_protocol_search(conn, pid, "openalex", 5)

    informe = prisma_report.build_report(conn, pid)

    assert "# Informe de revisión" in informe
    assert "Diagrama de flujo PRISMA 2020" in informe
    assert "Lista de verificación PRISMA 2020" in informe
    assert "Scopus" in informe, "debe declarar que no cubre Scopus/WoS"
    assert "Revisión X" in informe


def test_endpoints_prisma(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "prisma.db")
    conn = db.connect()
    db.init_db(conn)
    pid = db.save_protocol(conn, {"title": "P", "research_question": "q"})
    conn.close()

    client = TestClient(api_main.app)

    r1 = client.get(f"/api/review/protocol/{pid}/prisma-checklist")
    assert r1.status_code == 200
    assert r1.json()["total"] == 42

    r2 = client.get(f"/api/review/protocol/{pid}/prisma-report?format=md")
    assert r2.status_code == 200
    assert "text/markdown" in r2.headers["content-type"]
    assert "# Informe de revisión" in r2.text

    r3 = client.get(f"/api/review/protocol/{pid}/prisma-report?format=json")
    assert r3.status_code == 200
    assert r3.json()["checklist"]["total"] == 42
