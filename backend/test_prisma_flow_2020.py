"""Pruebas del diagrama de flujo PRISMA 2020 (identificación y duplicados estrictos).

Motivo (22-09-2026): el campo `duplicates_detected` del diagrama se calculaba sobre **toda** la
tabla `articles` (todos los protocolos y usuarios) y siempre daba 0, porque `articles.doi` es
UNIQUE. Estas pruebas fijan el comportamiento correcto: identificación por protocolo desde el
registro de búsquedas y duplicados removidos = identificados − registros únicos.
"""
import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from radar import config, db
from radar.api import main as api_main
from radar.harvester import live_probe


@contextmanager
def patch_probes(openalex, openaire, dialnet):
    """Sustituye las tres sondas en vivo por resultados fijos."""
    with patch("radar.harvester.live_probe._probe_openalex",
               return_value=(openalex, len(openalex))), \
         patch("radar.harvester.live_probe._probe_openaire", return_value=openaire), \
         patch("radar.harvester.live_probe._probe_dialnet", return_value=dialnet):
        yield


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


def test_duplicados_removidos_por_protocolo():
    conn = _conn()
    pid = db.save_protocol(conn, {"title": "P", "research_question": "q"})
    db.log_protocol_search(conn, pid, "openalex", 6)
    db.log_protocol_search(conn, pid, "openaire", 3)
    db.log_protocol_search(conn, pid, "dialnet", 1)
    for i in range(7):
        db.save_screening(conn, pid, doi=f"10.1/x{i}", decision="pending")

    flow = db.screening_flow_counts(conn, pid)

    assert flow["total_identified"] == 10
    assert flow["duplicates_detected"] == 3
    assert flow["prisma_2020"]["identificacion"]["total"] == 10
    assert flow["prisma_2020"]["identificacion"]["bases_de_datos"]["openalex"] == 6
    assert flow["prisma_2020"]["removidos_antes_del_cribado"]["duplicados"] == 3
    assert flow["prisma_2020"]["cribado"]["registros_unicos"] == 7


def test_identificacion_no_se_mezcla_entre_protocolos():
    conn = _conn()
    p1 = db.save_protocol(conn, {"title": "P1"})
    p2 = db.save_protocol(conn, {"title": "P2"})
    db.log_protocol_search(conn, p1, "openalex", 5)
    db.log_protocol_search(conn, p2, "openalex", 99)

    assert db.screening_flow_counts(conn, p1)["total_identified"] == 5
    assert db.screening_flow_counts(conn, p2)["total_identified"] == 99


def test_sin_busquedas_registradas_identificacion_es_cero():
    conn = _conn()
    pid = db.save_protocol(conn, {"title": "P"})
    for i in range(4):
        db.save_screening(conn, pid, doi=f"10.1/y{i}", decision="pending")

    flow = db.screening_flow_counts(conn, pid)

    # Sin registro de búsqueda no se inventa identificación; los duplicados no pueden ser negativos.
    assert flow["total_identified"] == 0
    assert flow["duplicates_detected"] == 0
    assert flow["prisma_2020"]["cribado"]["registros_unicos"] == 4


def test_registro_y_listado_de_busquedas():
    conn = _conn()
    pid = db.save_protocol(conn, {"title": "P"})
    db.log_protocol_search(conn, pid, "openalex", 3, query="ciencia ciudadana",
                           year_from=2005, year_to=2025)
    db.log_protocol_search(conn, pid, "dialnet", 2, query="ciencia ciudadana")

    busquedas = db.list_protocol_searches(conn, pid)

    assert len(busquedas) == 2
    fuentes = {b["source"]: b for b in busquedas}
    assert fuentes["openalex"]["year_from"] == 2005
    assert fuentes["openalex"]["year_to"] == 2025
    assert fuentes["openalex"]["query"] == "ciencia ciudadana"


def test_probe_cuenta_crudos_y_duplicados_intra():
    mock_oa = [
        {"title": "Estudio A", "doi": "10.1/a", "year": 2024,
         "source_engine": "openalex", "authors": [], "keywords": []},
        {"title": "Estudio A repetido", "doi": "10.1/a", "year": 2024,
         "source_engine": "openalex", "authors": [], "keywords": []},
        {"title": "Estudio B", "doi": "10.1/b", "year": 2024,
         "source_engine": "openalex", "authors": [], "keywords": []},
    ]
    mock_aire = [
        {"title": "Estudio B en OpenAIRE", "doi": "10.1/b", "year": 2024,
         "source_engine": "openaire", "authors": [], "keywords": []},
    ]
    with patch_probes(mock_oa, mock_aire, []):
        res = live_probe.probe_topic("ciencia ciudadana")

    assert res["fuentes_crudas"]["openalex"] == 3
    assert res["fuentes_crudas"]["openaire"] == 1
    assert res["duplicados_intra_busqueda"] == 2
    assert len(res["articles"]) == 2


# ── Endpoints: la búsqueda queda registrada y el diagrama la expone ─────────

def test_harvest_search_registra_una_fila_por_fuente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "prisma2020.db")
    conn = db.connect()
    db.init_db(conn)
    pid = db.save_protocol(conn, {"title": "P", "research_question": "ciencia participativa"})
    conn.close()

    def _probe_falso(*args, **kwargs):
        return {"articles": [], "filtro_anios": {"activo": False},
                "consulta_usada": "ciencia participativa",
                "fuentes_crudas": {"openalex": 4, "openaire": 2, "dialnet": 1}}

    monkeypatch.setattr("radar.harvester.live_probe.probe_topic", _probe_falso)
    client = TestClient(api_main.app)
    res = client.post(f"/api/review/protocol/{pid}/harvest-search",
                      json={"query": "ciencia participativa"})
    assert res.status_code == 200

    conn = db.connect()
    busquedas = db.list_protocol_searches(conn, pid)
    conn.close()
    fuentes = {b["source"]: b["records_identified"] for b in busquedas}
    assert fuentes == {"openalex": 4, "openaire": 2, "dialnet": 1}


def test_flow_diagram_expone_prisma_2020_y_busquedas(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "prisma2020b.db")
    conn = db.connect()
    db.init_db(conn)
    pid = db.save_protocol(conn, {"title": "P"})
    db.log_protocol_search(conn, pid, "openalex", 8)
    db.save_screening(conn, pid, doi="10.1/z1", decision="pending")
    conn.close()

    client = TestClient(api_main.app)
    res = client.get(f"/api/review/protocol/{pid}/flow-diagram")
    assert res.status_code == 200
    datos = res.json()
    assert datos["prisma_2020"]["identificacion"]["total"] == 8
    assert datos["prisma_2020"]["removidos_antes_del_cribado"]["duplicados"] == 7
    assert len(datos["busquedas"]) == 1


# ── Segunda etapa (texto completo), no destructiva ──────────────────────────

def test_flujo_una_etapa_incluido_es_final():
    conn = _conn()
    pid = db.save_protocol(conn, {"title": "P"})
    db.save_screening(conn, pid, doi="10.1/a", decision="included")
    db.save_screening(conn, pid, doi="10.1/b", decision="excluded")

    flow = db.screening_flow_counts(conn, pid)
    p = flow["prisma_2020"]

    assert p["segunda_etapa_implementada"] is False
    assert p["cribado"]["informes_buscados"] is None
    assert p["incluidos"]["estudios"] == 1
    assert flow["included"] == 1


def test_flujo_dos_etapas():
    conn = _conn()
    pid = db.save_protocol(conn, {"title": "P"})
    db.log_protocol_search(conn, pid, "openalex", 10)
    for i in range(5):
        db.save_screening(conn, pid, doi=f"10.1/inc{i}", decision="included", stage="title_abstract")
    for i in range(3):
        db.save_screening(conn, pid, doi=f"10.1/exc{i}", decision="excluded", stage="title_abstract")
    for i in range(2):
        db.save_screening(conn, pid, doi=f"10.1/dud{i}", decision="maybe", stage="title_abstract")
    # Segunda pasada sobre los 5 que avanzaron: 3 incluidos, 1 excluido, 1 no recuperado
    for i in range(3):
        db.save_screening(conn, pid, doi=f"10.1/inc{i}", decision="included", stage="full_text")
    db.save_screening(conn, pid, doi="10.1/inc3", decision="excluded", stage="full_text")
    db.save_screening(conn, pid, doi="10.1/inc4", decision="not_retrieved", stage="full_text")

    p = db.screening_flow_counts(conn, pid)["prisma_2020"]

    assert p["segunda_etapa_implementada"] is True
    assert p["cribado"]["registros_unicos"] == 10
    assert p["cribado"]["registros_cribados"] == 10
    assert p["cribado"]["registros_excluidos"] == 3
    assert p["cribado"]["informes_buscados"] == 7
    assert p["cribado"]["informes_no_recuperados"] == 1
    assert p["cribado"]["informes_evaluados"] == 4
    assert p["cribado"]["informes_excluidos"] == 1
    assert p["incluidos"]["estudios"] == 3


def test_misma_obra_dos_etapas_dos_filas():
    conn = _conn()
    pid = db.save_protocol(conn, {"title": "P"})
    db.save_screening(conn, pid, doi="10.1/a", decision="included", stage="title_abstract")
    db.save_screening(conn, pid, doi="10.1/a", decision="excluded", stage="full_text")

    filas = conn.execute(
        "SELECT stage FROM article_screenings WHERE protocol_id = ?", (pid,)).fetchall()
    assert len(filas) == 2


def test_stage_invalido_rechazado():
    conn = _conn()
    pid = db.save_protocol(conn, {"title": "P"})
    with pytest.raises(ValueError):
        db.save_screening(conn, pid, doi="10.1/x", decision="included", stage="inexistente")


def test_init_db_no_revienta_con_dois_que_chocan_al_minusculizar():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    conn.execute("INSERT INTO articles (doi, title, source) VALUES ('openalex:W1', 'A', 'openalex')")
    conn.execute("INSERT INTO articles (doi, title, source) VALUES ('openalex:w1', 'A dup', 'openalex')")
    conn.commit()

    # Antes lanzaba IntegrityError (no capturado) y abortaba init_db.
    db.init_db(conn)

    n = conn.execute("SELECT COUNT(*) FROM articles WHERE LOWER(doi) = 'openalex:w1'").fetchone()[0]
    assert n == 2, "las dos filas sobreviven; la que choca no se baja"


def test_migracion_conserva_cribados_y_permite_dos_etapas():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Esquema ANTIGUO: una sola etapa, UNIQUE(protocol_id, doi)
    conn.executescript("""
        CREATE TABLE article_screenings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            protocol_id INTEGER NOT NULL,
            article_id INTEGER,
            doi TEXT,
            decision TEXT NOT NULL DEFAULT 'pending',
            reason TEXT,
            screened_by TEXT DEFAULT 'researcher',
            created_at TEXT,
            UNIQUE(protocol_id, doi)
        );
        INSERT INTO article_screenings (protocol_id, doi, decision, reason)
            VALUES (1, '10.1/a', 'included', 'Ensayo clave');
    """)
    conn.commit()

    db.init_db(conn)

    filas = conn.execute("SELECT * FROM article_screenings").fetchall()
    assert len(filas) == 1, "la migración no debe perder cribados"
    assert filas[0]["decision"] == "included"
    assert filas[0]["reason"] == "Ensayo clave"
    assert filas[0]["stage"] == "title_abstract"
    # Y ahora la misma obra admite una segunda fila en la otra etapa
    db.save_screening(conn, 1, doi="10.1/a", decision="excluded", stage="full_text")
    assert conn.execute("SELECT COUNT(*) FROM article_screenings").fetchone()[0] == 2
