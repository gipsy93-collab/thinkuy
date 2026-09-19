"""Comportamiento de SERVIDOR: buscar es una lectura; solo transferir a una revisión persiste.

Motivo medido (18-09-2026): una sola búsqueda clínica metió **95 artículos de oncología** en el
catálogo de comunicación del investigador (el catálogo pasó de 12.039 a 12.106 en un día). En un
despliegue abierto eso es inaceptable: el catálogo no debe crecer con lo que cada visitante
escribe en el buscador, y menos aún compartirse entre usuarios.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from radar import config, db
from radar.api import main as api_main
from radar.harvester import live_probe

ARTICULO = {
    "title": "Pembrolizumab en carcinoma renal: una revisión",
    "doi": "10.1000/servidor.1",
    "abstract": "Resumen de prueba sobre inmunoterapia.",
    "year": 2024,
    "source": "openalex",
    "source_engine": "openalex",
    "authors": [{"given": "Ana", "family": "Pérez"}],
    "keywords": ["pembrolizumab", "inmunoterapia"],
}


@pytest.fixture()
def base_temporal(tmp_path, monkeypatch):
    """Base en archivo temporal: la API abre y cierra sus propias conexiones."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "prueba.db")
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    return tmp_path


def _contar_articulos() -> int:
    conn = db.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    finally:
        conn.close()


def _respuesta_de_sonda(_: dict) -> dict:
    return {
        "data_source": "live_probe",
        "probe_engine": "Sonda Federada",
        "articles": [dict(ARTICULO)],
        "ecosystem": {"total_matched": 1, "sources": {"openalex_live": 1}, "top_journals": [],
                      "years": {"min": 2024, "max": 2024, "recent_count": 1}},
        "saturation": {"level": "niche", "label": "Frontera", "description": "d", "review_count": 0},
        "top_authors": [], "suggested_keywords": [],
        "consulta_usada": "pembrolizumab", "relajada": False,
        "intentos": [{"consulta": "pembrolizumab", "resultados": 1}],
    }


def test_por_defecto_no_se_indexa_al_buscar():
    """El comportamiento por defecto es el de un servidor: buscar no escribe."""
    assert config.INDEX_LIVE_RESULTS is False


def test_la_busqueda_en_vivo_no_escribe_en_el_catalogo(base_temporal, monkeypatch):
    monkeypatch.setattr(live_probe, "probe_topic", lambda **kw: _respuesta_de_sonda(kw))
    antes = _contar_articulos()

    respuesta = TestClient(api_main.app).post(
        "/api/librarian/assist", json={"inquiry": "pembrolizumab", "limit": 5})

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert len(datos["articles"]) == 1, "la búsqueda debe devolver resultados"
    assert _contar_articulos() == antes, "pero NO debe escribir nada en el catálogo"


def test_la_busqueda_no_devuelve_ids_internos_cuando_no_indexa(base_temporal, monkeypatch):
    """Sin escritura no hay id interno: la interfaz debe poder trabajar con eso."""
    monkeypatch.setattr(live_probe, "probe_topic", lambda **kw: _respuesta_de_sonda(kw))

    datos = TestClient(api_main.app).post(
        "/api/librarian/assist", json={"inquiry": "pembrolizumab", "limit": 5}).json()

    assert datos["articles"][0].get("id") is None


def test_transferir_a_cribado_SI_persiste(base_temporal, monkeypatch):
    """La escritura ocurre en la acción explícita: transferir resultados a una revisión."""
    conn = db.connect()
    pid = db.save_protocol(conn, {"title": "Revisión de prueba", "research_question": "¿X?"})
    conn.close()
    antes = _contar_articulos()

    respuesta = TestClient(api_main.app).post(
        f"/api/review/protocol/{pid}/screen-batch",
        json={"items": [{"doi": ARTICULO["doi"], "decision": "pending", "article": ARTICULO}]})

    assert respuesta.status_code == 200
    assert _contar_articulos() == antes + 1, "transferir sí indexa el artículo"

    conn = db.connect()
    try:
        fila = conn.execute(
            "SELECT article_id FROM article_screenings WHERE protocol_id = ? AND doi = ?",
            (pid, ARTICULO["doi"])).fetchone()
        assert fila["article_id"], "y queda enlazado para el cribado"
        titulo = conn.execute("SELECT title FROM articles WHERE doi = ?",
                              (ARTICULO["doi"],)).fetchone()["title"]
        assert titulo.startswith("Pembrolizumab")
    finally:
        conn.close()


def test_transferir_sin_articulo_no_rompe(base_temporal):
    """Compatibilidad: un item sin payload sigue registrando la decisión (sin indexar)."""
    conn = db.connect()
    pid = db.save_protocol(conn, {"title": "Otra revisión", "research_question": "¿Y?"})
    conn.close()

    respuesta = TestClient(api_main.app).post(
        f"/api/review/protocol/{pid}/screen-batch",
        json={"items": [{"doi": "10.1000/sin.payload", "decision": "pending"}]})

    assert respuesta.status_code == 200
    conn = db.connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM article_screenings WHERE protocol_id = ?",
                         (pid,)).fetchone()[0]
        assert n == 1
    finally:
        conn.close()
