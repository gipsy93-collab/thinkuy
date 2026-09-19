"""Pruebas del flujo de cribado PRISMA a VOLUMEN REALISTA.

Motivo (18-09-2026): el cribado se colgaba y los botones parecían muertos. La causa era que
`screening_flow_counts` enlazaba por `LOWER(s.doi) = LOWER(a.doi)` —sin índice posible— y
escaneaba la tabla de artículos por cada cribado (232,86 s medidos con 7.817 cribados).
`test_systematic_review.py` **no probaba el cribado**, y por eso "60/60 en verde" ocultó la
regresión. Estas pruebas cubren el flujo y le imponen un techo de tiempo.
"""
import sqlite3
import time

import pytest

from radar import db

# Techo deliberadamente holgado: el JOIN por clave primaria tarda milisegundos. La versión
# lenta tardaba decenas de segundos con este volumen, así que la prueba lo detecta sin ser
# frágil en una máquina cargada.
TOPE_SEGUNDOS = 2.0

ARTICULOS = 4000
CRIBADOS = 3000
SIN_ENLAZAR = 10  # cribados con DOI que no existe en el catálogo (caso real: 42 de 8.013)


@pytest.fixture()
def conn_lleno():
    """Base en memoria con volumen realista: 4.000 artículos y 3.000 cribados.

    Reproduce la distribución real: casi todos los cribados con `article_id` resuelto (en
    producción, 7.971 de 8.013) y unos pocos cuyo DOI no está en el catálogo.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)

    articulos = [
        (f"10.1000/art.{i}", f"Artículo {i} sobre comunicación y salud", "abstract",
         "openalex" if i % 2 else "scielo")
        for i in range(ARTICULOS)
    ]
    conn.executemany(
        "INSERT INTO articles (doi, title, abstract, source) VALUES (?, ?, ?, ?)", articulos)
    conn.commit()

    pid = db.save_protocol(conn, {"title": "Protocolo de prueba a volumen",
                                  "research_question": "¿Cómo se criba a escala?"})
    filas = []
    for i in range(CRIBADOS):
        enlazado = i < CRIBADOS - SIN_ENLAZAR
        doi = f"10.1000/art.{i}" if enlazado else f"10.1000/huerfano.{i}"
        filas.append((pid, i + 1 if enlazado else None, doi,
                      ["pending", "included", "excluded", "maybe"][i % 4], None, "test", "2026-01-01"))
    conn.executemany(
        """INSERT INTO article_screenings (protocol_id, article_id, doi, decision, reason, screened_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""", filas)
    conn.commit()
    yield conn, pid
    conn.close()


# ── El flujo, con techo de tiempo ───────────────────────────────────────────

def test_los_conteos_prisma_son_rapidos(conn_lleno):
    """Este es el endpoint que colgaba la interfaz detrás de cada clic."""
    conn, pid = conn_lleno

    t0 = time.time()
    conteos = db.screening_flow_counts(conn, pid)
    transcurrido = time.time() - t0

    assert transcurrido < TOPE_SEGUNDOS, f"los conteos tardaron {transcurrido:.1f} s"
    assert conteos["total_identified"] == CRIBADOS
    assert conteos["pending"] + conteos["included"] + conteos["excluded"] + conteos["maybe"] == CRIBADOS
    assert sum(conteos["sources"].values()) == CRIBADOS, "el desglose por fuente pierde filas"
    assert conteos["sources"].get("sin_articulo") == SIN_ENLAZAR, \
        "los cribados sin artículo enlazado deben declararse, no desaparecer"


def test_el_listado_de_cribados_es_rapido_y_trae_los_metadatos(conn_lleno):
    conn, pid = conn_lleno

    t0 = time.time()
    filas = db.list_screenings(conn, pid, limit=500)
    transcurrido = time.time() - t0

    assert transcurrido < TOPE_SEGUNDOS, f"el listado tardó {transcurrido:.1f} s"
    assert len(filas) == 500
    con_titulo = [f for f in filas if f["title"] and f["title"].startswith("Artículo")]
    assert con_titulo, "debe venir el título del artículo, no solo el DOI"
    assert all(f["source"] in ("openalex", "scielo") for f in filas if f["source"])


def test_la_migracion_enlaza_los_cribados_sin_article_id(conn_lleno):
    """Un cribado guardado sin artículo debe quedar enlazado al arrancar la base."""
    conn, pid = conn_lleno
    conn.execute(
        """INSERT INTO article_screenings (protocol_id, doi, decision, screened_by, created_at)
           VALUES (?, '10.1000/art.3999', 'included', 'test', '2026-01-01')""", (pid,))
    conn.commit()

    db._migrate_screening_links(conn)

    fila = conn.execute(
        "SELECT article_id FROM article_screenings WHERE protocol_id = ? AND doi = '10.1000/art.3999'",
        (pid,)).fetchone()
    assert fila["article_id"], "el enlace por DOI normalizado debe rellenar article_id"


def test_guardar_decision_resuelve_el_articulo(conn_lleno):
    conn, pid = conn_lleno

    guardado = db.save_screening(conn, pid, doi="10.1000/art.777", decision="included",
                                 screened_by="test")

    assert guardado["article_id"], "save_screening debe resolver el article_id al guardar"
    assert guardado["decision"] == "included"
    # Y se puede actualizar la misma fila (UNIQUE protocol_id + doi)
    db.save_screening(conn, pid, doi="10.1000/art.777", decision="excluded", screened_by="test")
    assert db.screening_flow_counts(conn, pid)["excluded"] >= 1


def test_la_exportacion_enlaza_por_clave_primaria(conn_lleno):
    conn, pid = conn_lleno

    t0 = time.time()
    incluidos = db.export_protocol_articles(conn, pid, decision_filter="included")
    transcurrido = time.time() - t0

    assert transcurrido < TOPE_SEGUNDOS, f"la exportación tardó {transcurrido:.1f} s"
    assert incluidos, "debe haber artículos incluidos"
    con_metadatos = [a for a in incluidos if str(a.get("title", "")).startswith("Artículo")]
    assert con_metadatos, "debe venir el título del artículo enlazado"
    # Ni pérdidas ni duplicados: se exporta exactamente lo que está incluido.
    incluidos_en_bd = conn.execute(
        "SELECT COUNT(*) FROM article_screenings WHERE protocol_id = ? AND decision = 'included'",
        (pid,)).fetchone()[0]
    assert len(incluidos) == incluidos_en_bd


def test_la_exportacion_sin_filtro_no_se_dispara(conn_lleno):
    """Sin filtro son 3.000 DOI: con el `IN (...)` anterior esto era el peor caso."""
    conn, pid = conn_lleno

    t0 = time.time()
    todos = db.export_protocol_articles(conn, pid, decision_filter=None)
    transcurrido = time.time() - t0

    assert transcurrido < TOPE_SEGUNDOS, f"la exportación completa tardó {transcurrido:.1f} s"
    assert len(todos) == CRIBADOS
