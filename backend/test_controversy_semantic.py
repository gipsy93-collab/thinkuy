"""Pruebas para la clasificación retórica y de controversias (controversy.py)."""
import sqlite3
import pytest
from radar import controversy, librarian

def test_classify_stance_heuristic():
    assert controversy.classify_stance("Este estudio confirma la hipótesis empírica") == "supporting"
    assert controversy.classify_stance("Los resultados contradicen la teoría clásica") == "contradicting"
    assert controversy.classify_stance("Se presenta una escala y validación psicométrica") == "methodological"
    assert controversy.classify_stance("Revisión general sobre el estado del arte") == "mixed"


def test_analyze_topic_heuristic(monkeypatch):
    # Forzar que el LLM no esté disponible
    monkeypatch.setattr(librarian, "available", lambda: False)

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY,
            title TEXT,
            abstract TEXT,
            doi TEXT,
            year INTEGER,
            journal_title TEXT,
            cited_by INTEGER,
            pub_date TEXT,
            keywords TEXT,
            authors TEXT
        )
    """)
    conn.execute("""
        INSERT INTO articles (id, title, abstract, doi, year, journal_title, cited_by, pub_date)
        VALUES (1, 'Fake news y desinformación', 'Este trabajo confirma los efectos de polarización.', '10.1/a', 2024, 'Revista Com', 10, '2024-01-01')
    """)

    res = controversy.analyze_topic(conn, "desinformacion", limit=5)
    assert res["model_mode"] == "heuristic_fallback"
    assert len(res["supporting"]) == 1
    assert res["supporting"][0]["stance_label"] == "Posible consenso"
    assert res["supporting"][0]["confidence"] == "heuristic"
    conn.close()


def test_analyze_topic_ai_mock(monkeypatch):
    # Simular LLM disponible con respuesta semántica
    monkeypatch.setattr(librarian, "available", lambda: True)
    monkeypatch.setattr(
        librarian,
        "classify_topic_stances_ai",
        lambda items, topic, batch_size=15: [
            {"stance": "contradicting", "rationale": "Evidencia opuesta al consenso", "confidence": "high"}
        ]
    )

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY,
            title TEXT,
            abstract TEXT,
            doi TEXT,
            year INTEGER,
            journal_title TEXT,
            cited_by INTEGER,
            pub_date TEXT,
            keywords TEXT,
            authors TEXT
        )
    """)
    conn.execute("""
        INSERT INTO articles (id, title, abstract, doi, year, journal_title, cited_by, pub_date)
        VALUES (1, 'Fact-checking experimental', 'Evaluación empírica en laboratorio.', '10.1/b', 2024, 'Revista Com', 15, '2024-01-01')
    """)

    res = controversy.analyze_topic(conn, "fact-checking", limit=5)
    assert res["model_mode"] == "ai_semantic"
    assert len(res["contradicting"]) == 1
    assert res["contradicting"][0]["stance_label"] == "Posible disenso"
    assert res["contradicting"][0]["confidence"] == "high"
    assert res["contradicting"][0]["rationale"] == "Evidencia opuesta al consenso"
    conn.close()
