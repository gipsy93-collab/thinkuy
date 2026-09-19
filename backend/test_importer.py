"""Pruebas unitarias para el módulo de importación, auditoría y diagnóstico inteligente."""
import io
import sqlite3
import pytest
from radar import importer, db

def test_inspect_file_csv_diagnostics():
    csv_content = (
        "Title,Author,Year,Citation count,Open access,Abstract\n"
        "Citizen science governance,Author One|Author Two,2021,45,Open Access,An abstract about governance\n"
        "Another paper,Author Three,2022,12,Closed,Second abstract here\n"
    ).encode("utf-8")

    res = importer.inspect_file(csv_content, "test.csv")
    assert res["valid"] is True
    assert res["total_rows"] == 2
    assert res["coverage"]["title_pct"] == 100.0
    assert res["coverage"]["abstract_pct"] == 100.0
    assert res["coverage"]["doi_pct"] == 0.0
    assert res["coverage"]["journal_pct"] == 0.0
    assert "DOIs normalizados" in res["recommendation"]["missing_fields"]
    assert res["recommendation"]["hybrid_enrichment_available"] is True


def test_import_csv_to_protocol_and_screening():
    conn = db.connect(":memory:")
    db.init_db(conn)

    # Crear protocolo de prueba
    proto_id = db.save_protocol(
        conn,
        {
            "title": "Protocolo de Prueba CSV",
            "research_question": "¿Cuáles son los marcos normativos?",
            "inclusion_criteria": "Artículos sobre gobernanza",
            "exclusion_criteria": "Fuera de tema",
            "created_by": "test_user",
        }
    )

    csv_content = (
        "Title,Author,Year,Citation count,Open access,Abstract\n"
        "Assessing data quality in citizen science,Margaret Kosmala,2016,1003,Open Access,Abstract one\n"
        "Citizen science public policy,Author B,2018,149,Open Access,Abstract two\n"
    ).encode("utf-8")

    res = importer.import_csv_to_protocol(conn, proto_id, csv_content, "openalex_sample.csv", source_label="openalex")
    assert res["status"] == "ok"
    assert res["imported_new"] == 2
    assert res["added_to_screening"] == 2

    # Verificar que los screenings se crearon como pending
    screenings = db.list_screenings(conn, proto_id)
    assert len(screenings) == 2
    for s in screenings:
        assert s["decision"] == "pending"
        assert s["protocol_id"] == proto_id
        # Verificar el artículo asociado en la tabla articles
        art = conn.execute("SELECT * FROM articles WHERE id = ?", (s["article_id"],)).fetchone()
        assert art is not None
        assert art["source"] == "openalex"
