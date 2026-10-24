"""Pruebas del Snowballing por DOI con expansión en vivo (OpenAlex).

Motivo (medido 22-09-2026): sin la vía en vivo, `expand_seed_graph` solo caminaba por citas
internas del catálogo y devolvía **solo la semilla** (6/6 semillas -> expandidos=1). Estas
pruebas fijan que las referencias (`referenced_works`) y los citantes (`cites:`) se consultan.
"""
import sqlite3
from unittest.mock import patch

from radar import citation_graph as cg
from radar import db


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass


def _item(oaid, title, year, doi=None):
    return {"id": f"https://openalex.org/{oaid}", "title": title,
            "publication_year": year, "doi": doi, "referenced_works": []}


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    db.upsert_article(conn, {
        "title": "Semilla", "source": "openalex", "doi": "10.1/seed",
        "openalex_id": "W1", "referenced_ids": ["W10", "W11"], "cited_by": 5, "year": 2020,
    })
    return conn


def test_snowball_live_backward_y_forward():
    conn = _conn()
    with patch("httpx.Client", _FakeClient), \
         patch("radar.harvester.openalex.get_works_by_ids",
               return_value=[_item("W10", "Ancestro A", 1999, "10.1/a"),
                             _item("W11", "Ancestro B", 2005, "10.1/b")]), \
         patch("radar.harvester.openalex.get_citing_works",
               return_value=[_item("W20", "Descendiente C", 2024, "10.1/c")]):
        res = cg.expand_seed_graph(conn, seed_doi="10.1/seed", direction="both", limit=15)

    arts = res["articles"]
    relaciones = {a.get("relation") for a in arts}
    assert res["expanded_count"] == 4  # semilla + 2 ancestros + 1 descendiente
    assert "cited_by_seed (ancestor)" in relaciones
    assert "cites_seed (descendant)" in relaciones
    assert any(a.get("is_seed") for a in arts)


def test_snowball_direccion_backward_solo():
    conn = _conn()
    with patch("httpx.Client", _FakeClient), \
         patch("radar.harvester.openalex.get_works_by_ids",
               return_value=[_item("W10", "Ancestro A", 1999, "10.1/a")]), \
         patch("radar.harvester.openalex.get_citing_works") as cit:
        res = cg.expand_seed_graph(conn, seed_doi="10.1/seed", direction="backward", limit=15)

    assert res["expanded_count"] == 2
    assert all(a.get("relation") != "cites_seed (descendant)" for a in res["articles"])
    cit.assert_not_called()


def test_snowball_resuelve_semilla_externa_en_vivo():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    with patch("httpx.Client", _FakeClient), \
         patch("radar.harvester.openalex.get_work_by_doi",
               return_value=_item("W99", "Semilla externa", 2021, "10.9/externa")), \
         patch("radar.harvester.openalex.get_works_by_ids", return_value=[]), \
         patch("radar.harvester.openalex.get_citing_works", return_value=[]):
        res = cg.expand_seed_graph(conn, seed_doi="10.9/externa", direction="both", limit=10)

    assert res.get("error") is None
    assert res["expanded_count"] == 1
    assert res["seed"]["title"] == "Semilla externa"


def test_snowball_semilla_inexistente_declara_error():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    with patch("httpx.Client", _FakeClient), \
         patch("radar.harvester.openalex.get_work_by_doi", return_value=None):
        res = cg.expand_seed_graph(conn, seed_doi="10.9/noexiste", direction="both", limit=10)

    assert "error" in res


# ── Grafo en vivo (engrosar SPC/co-citación) ────────────────────────────────

def test_build_live_graph_arma_aristas():
    corpus = [{"id": "https://openalex.org/W1", "title": "Corpus A", "publication_year": 2020,
               "doi": "https://doi.org/10.1/a", "referenced_works": ["https://openalex.org/W9"]}]
    refs = [{"id": "https://openalex.org/W9", "title": "Referencia", "publication_year": 1999,
             "doi": "https://doi.org/10.1/ref"}]
    with patch("httpx.Client", _FakeClient), \
         patch("radar.harvester.openalex.get_works_by_dois", return_value=corpus), \
         patch("radar.harvester.openalex.get_works_by_ids", return_value=refs):
        conn = cg.build_live_graph(["10.1/a"])

    edges = cg.build_edges(conn)
    stats = cg.citation_stats(conn)
    assert stats["nodes"] == 2
    assert len(edges) == 1, "la referencia debe crear la arista corpus -> referencia"
    conn.close()
