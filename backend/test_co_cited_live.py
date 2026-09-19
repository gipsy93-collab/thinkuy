"""Pruebas unitarias para co-citación con soporte API-First en vivo (citation_graph.py)."""
import sqlite3
import pytest
from radar import citation_graph

def test_co_cited_local():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY,
            title TEXT,
            doi TEXT,
            year INTEGER,
            journal_title TEXT,
            source TEXT,
            source_id TEXT,
            openalex_id TEXT,
            s2_paper_id TEXT,
            referenced_ids TEXT,
            s2_references TEXT
        )
    """)
    # Insertar dos artículos que comparten referencias
    conn.execute("""
        INSERT INTO articles (id, title, doi, year, journal_title, referenced_ids, s2_references)
        VALUES (1, 'Paper A', '10.1/a', 2023, 'Revista X', '["W123", "W456"]', '[]'),
               (2, 'Paper B', '10.1/b', 2024, 'Revista Y', '["W123", "W999"]', '[]')
    """)

    results = citation_graph.co_cited(conn, "10.1/a", limit=5, mode="local")
    assert len(results) == 1
    assert results[0]["doi"] == "10.1/b"
    assert results[0]["shared_refs"] == 1
    conn.close()


def test_co_cited_live_mock(monkeypatch):
    class MockResponse:
        def __init__(self, data, status_code=200):
            self._data = data
            self.status_code = status_code

        def json(self):
            return self._data

    class MockClient:
        def get(self, url, params=None, headers=None):
            if "works/https://doi.org/" in url:
                return MockResponse({"related_works": ["https://openalex.org/W98765"]})
            else:
                return MockResponse({
                    "results": [
                        {
                            "title": "Related OpenAlex Paper",
                            "doi": "https://doi.org/10.1000/live.test",
                            "publication_year": 2025,
                            "primary_location": {"source": {"display_name": "Global Open Journal"}},
                            "cited_by_count": 42,
                        }
                    ]
                })

        def close(self):
            pass

    client = MockClient()
    res = citation_graph.co_cited_live("10.1000/some.paper", limit=5, client=client)
    assert len(res) == 1
    assert res[0]["title"] == "Related OpenAlex Paper"
    assert res[0]["doi"] == "10.1000/live.test"
    assert res[0]["source"] == "openalex_live"
    assert res[0]["cited_by"] == 42


def test_detect_cocitation_clusters_deduplication():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY,
            title TEXT,
            doi TEXT,
            year INTEGER,
            journal_title TEXT,
            cited_by INTEGER,
            keywords TEXT,
            source TEXT,
            source_id TEXT,
            openalex_id TEXT,
            s2_paper_id TEXT,
            referenced_ids TEXT,
            s2_references TEXT
        )
    """)
    # 2 artículos citan W100 y W200.
    # El artículo 1 tiene openalex_id 'W100' y doi '10.123/w100'
    conn.execute("""
        INSERT INTO articles (id, title, doi, year, journal_title, cited_by, openalex_id, referenced_ids, s2_references)
        VALUES 
        (1, 'Foundational Work', '10.123/w100', 2020, 'Top Journal', 50, 'W100', '["W100", "doi:10.123/w100", "W200"]', '[]'),
        (2, 'Second Work', '10.123/w200', 2021, 'Second Journal', 30, 'W200', '["W100", "doi:10.123/w100", "W200"]', '[]')
    """)
    clusters = citation_graph.detect_cocitation_clusters(conn, threshold=1, min_size=2)
    assert len(clusters) >= 1
    c = clusters[0]
    # Comprobar que no hay artículos duplicados en representative_articles
    rep_ids = [a["id"] for a in c["representative_articles"]]
    assert len(rep_ids) == len(set(rep_ids)), f"Duplicados encontrados en representative_articles: {rep_ids}"
    assert c["catalog_count"] == len(set(rep_ids))
    conn.close()

