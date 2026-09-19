"""Pruebas del radar: filtros de autores, descubrimiento en vivo y vigilancia continua."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from radar import author_match, config, db, network, proximity, topics
from radar.harvester import live_search


def make_article(title, doi, authors, abstract="Estudio sobre desinformacion en redes sociales"):
    return {
        "title": title,
        "abstract": abstract,
        "keywords": ["desinformacion", "redes sociales"],
        "authors": authors,
        "journal_title": "Revista de prueba",
        "year": 2026,
        "pub_date": "2026-01-15",
        "lang": "es",
        "url": f"https://doi.org/{doi}",
        "source": "test",
        "source_id": doi,
        "doi": doi,
    }


class RadarManagementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory(prefix="thinkuy-radar-test-")
        cls._previous_db = config.DB_PATH
        config.DB_PATH = Path(cls._directory.name) / "radar-test.db"
        cls.conn = db.connect()
        db.init_db(cls.conn)
        _, target_id = db.upsert_article(cls.conn, make_article(
            "Desinformacion en redes sociales",
            "10.0/existing-one",
            [{"given": "Ana", "family": "Torres"}, {"given": "Bruno", "family": "Lima"}],
        ))
        cls.target_id = target_id
        _, cls.orcid_target_id = db.upsert_article(cls.conn, make_article(
            "Perfil con ORCID verificable",
            "10.0/orcid-target",
            [{"given": "Coincidencia", "family": "Persona", "orcid": "https://orcid.org/0000-0002-1825-0110"}],
        ))
        db.upsert_article(cls.conn, make_article(
            "Homónimo con ORCID distinto",
            "10.0/homonym-different",
            [{"given": "Coincidencia", "family": "Persona", "orcid": "https://orcid.org/0000-0002-1825-0111"}],
        ))
        db.upsert_article(cls.conn, make_article(
            "Mas desinformacion en redes sociales",
            "10.0/extra-one",
            [{"given": "Diana", "family": "Solo"}],
        ))
        db.upsert_article(cls.conn, make_article(
            "Verificacion de desinformacion en redes sociales",
            "10.0/orcid-one",
            [{"given": "Elena", "family": "Verificada", "orcid": "https://orcid.org/0000-0002-1825-0097"}],
        ))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.conn.close()
        finally:
            config.DB_PATH = cls._previous_db
            cls._directory.cleanup()

    def setUp(self):
        network.invalidate_network_cache()

    def test_radar_returns_nodes_and_edges(self):
        result = proximity.radar(self.conn, topic="Desinformacion", limit=10)
        self.assertGreater(len(result["nodes"]), 0)
        self.assertGreaterEqual(len(result["edges"]), 0)
        self.assertIn("resolved_included", result)
        node = result["nodes"][0]
        self.assertTrue(node["works_list"])
        self.assertTrue(node["top_keywords"])
        self.assertIn("desinformacion", {keyword.lower() for keyword in node["works_list"][0]["keywords"]})

    def test_radar_excludes_author(self):
        base = proximity.radar(self.conn, topic="Desinformacion", limit=10)
        author_id = base["nodes"][0]["id"]
        filtered = proximity.radar(self.conn, topic="Desinformacion", limit=10, excluded=[author_id])
        filtered_ids = {node["id"] for node in filtered["nodes"]}
        self.assertNotIn(author_id, filtered_ids)
        self.assertIn(author_id, filtered["excluded"])

    def test_radar_includes_below_minimum_works(self):
        target_key = network.author_key({"given": "Diana", "family": "Solo"})
        result = proximity.radar(self.conn, topic="Desinformacion", limit=10, min_works=2, included=["Diana Solo"])
        included_ids = {node["id"] for node in result["nodes"]}
        self.assertIn(target_key, included_ids)
        self.assertIn(target_key, result["resolved_included"])

    def test_radar_accepts_orcid_inclusion(self):
        result = proximity.radar(
            self.conn,
            topic="Desinformacion",
            limit=10,
            min_works=2,
            included=["0000-0002-1825-0097"],
        )
        included_ids = {node["id"] for node in result["nodes"]}
        self.assertIn("orcid:0000-0002-1825-0097", included_ids)
        self.assertEqual(
            next(node for node in result["nodes"] if node["id"] == "orcid:0000-0002-1825-0097")["identity_status"],
            "orcid-verified",
        )

    def test_excluded_takes_precedence_over_included(self):
        target_key = network.author_key({"given": "Diana", "family": "Solo"})
        result = proximity.radar(
            self.conn,
            topic="Desinformacion",
            limit=10,
            excluded=["Diana Solo"],
            included=["Diana Solo"],
        )
        included_ids = {node["id"] for node in result["nodes"]}
        self.assertNotIn(target_key, included_ids)

    def test_radar_endpoint_accepts_filter_lists(self):
        from fastapi.testclient import TestClient
        from radar.api import main as api_main

        with TestClient(api_main.app) as client:
            base = client.get("/api/radar", params={"topic": "Desinformacion", "limit": 10})
            self.assertEqual(base.status_code, 200)
            author_id = base.json()["nodes"][0]["id"]
            filtered = client.get("/api/radar", params={
                "topic": "Desinformacion",
                "limit": 10,
                "excluded": author_id,
                "included": "Diana Solo",
            })
        self.assertEqual(filtered.status_code, 200)
        payload = filtered.json()
        self.assertNotIn(author_id, {node["id"] for node in payload["nodes"]})
        self.assertIn(author_id, payload["excluded"])
        self.assertIn("resolved_included", payload)

    def test_author_match_does_not_merge_orcid_homonyms(self):
        result = author_match.find_author_matches(self.conn, article_id=self.orcid_target_id, limit=10)
        match_ids = {match["id"] for match in result["matches"]}
        self.assertIn("orcid:0000-0002-1825-0111", match_ids)
        self.assertNotIn("orcid:0000-0002-1825-0110", match_ids)

    def test_authors_suggest_endpoint_matches_name_and_orcid(self):
        from fastapi.testclient import TestClient
        from radar.api import main as api_main

        with TestClient(api_main.app) as client:
            by_name = client.get("/api/authors/suggest", params={"q": "Diana Solo"})
            by_orcid = client.get("/api/authors/suggest", params={"q": "0000-0002-1825-0097"})
        self.assertEqual(by_name.status_code, 200)
        self.assertEqual(by_orcid.status_code, 200)
        self.assertTrue(any(author["key"] == "solo diana" for author in by_name.json()["authors"]))
        self.assertTrue(any(author.get("orcid") == "0000-0002-1825-0097" for author in by_orcid.json()["authors"]))


class AuthorIdentityResolutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory(prefix="thinkuy-identity-test-")
        cls._previous_db = config.DB_PATH
        config.DB_PATH = Path(cls._directory.name) / "radar-identity-test.db"
        cls.conn = db.connect()
        db.init_db(cls.conn)
        db.upsert_article(cls.conn, make_article(
            "Primer estudio",
            "10.0/identity-a",
            [{"given": "Prueba", "family": "Persona", "orcid": "0000-0002-1825-0101"}],
        ))
        db.upsert_article(cls.conn, make_article(
            "Segundo estudio",
            "10.0/identity-b",
            [{"given": "Prueba", "family": "Persona", "orcid": "0000-0002-1825-0102"}],
        ))
        db.upsert_article(cls.conn, make_article(
            "Tercer estudio sin ORCID",
            "10.0/identity-ambiguous",
            [{"given": "Prueba", "family": "Persona"}],
        ))
        db.upsert_article(cls.conn, make_article(
            "Estudio con ORCID parcial",
            "10.0/identity-inferred",
            [{"given": "Unica", "family": "Persona", "orcid": "0000-0002-1825-0103"}],
        ))
        db.upsert_article(cls.conn, make_article(
            "Otro estudio con nombre equivalente",
            "10.0/identity-inferred-2",
            [{"given": "Unica", "family": "Persona"}],
        ))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.conn.close()
        finally:
            config.DB_PATH = cls._previous_db
            cls._directory.cleanup()

    def setUp(self):
        network.invalidate_network_cache()

    def test_same_name_with_different_orcids_is_not_merged(self):
        edges = network.build_author_edges(self.conn, min_works=1)
        self.assertIn("orcid:0000-0002-1825-0101", edges["authors"])
        self.assertIn("orcid:0000-0002-1825-0102", edges["authors"])
        self.assertIn("name:persona prueba:ambiguous", edges["authors"])
        self.assertEqual(edges["authors"]["name:persona prueba:ambiguous"]["identity_status"], "ambiguous")

    def test_missing_orcid_is_inferred_only_when_unique(self):
        edges = network.build_author_edges(self.conn, min_works=1)
        self.assertIn("orcid:0000-0002-1825-0103", edges["authors"])
        self.assertEqual(edges["authors"]["orcid:0000-0002-1825-0103"]["n"], 2)
        self.assertEqual(edges["authors"]["orcid:0000-0002-1825-0103"]["identity_status"], "orcid-verified")


class JournalRegistrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory(prefix="thinkuy-journal-test-")
        cls._previous_db = config.DB_PATH
        config.DB_PATH = Path(cls._directory.name) / "radar-journal-test.db"
        cls.conn = db.connect()
        db.init_db(cls.conn)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.conn.close()
        finally:
            config.DB_PATH = cls._previous_db
            cls._directory.cleanup()

    def test_journal_registration_is_idempotent(self):
        created, first_id = db.ensure_journal_from_article(
            self.conn, source="openalex", title="Revista en vivo", issn="1234-5678"
        )
        repeated, second_id = db.ensure_journal_from_article(
            self.conn, source="openalex", title="revista en vivo", issn="1234-5678"
        )
        invalid_created, invalid_id = db.ensure_journal_from_article(
            self.conn, source="openalex", title="", issn="no-es-issn"
        )
        self.assertTrue(created)
        self.assertFalse(repeated)
        self.assertEqual(first_id, second_id)
        self.assertFalse(invalid_created)
        self.assertIsNone(invalid_id)
        self.assertEqual(db.count_journals(self.conn), 1)


class LiveDiscoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory(prefix="thinkuy-live-test-")
        cls._previous_db = config.DB_PATH
        config.DB_PATH = Path(cls._directory.name) / "radar-live-test.db"
        cls.conn = db.connect()
        db.init_db(cls.conn)
        db.upsert_article(cls.conn, make_article(
            "Articulo previo sobre desinformacion",
            "10.0/existing-live",
            [{"given": "Existente", "family": "Uno"}],
        ))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.conn.close()
        finally:
            config.DB_PATH = cls._previous_db
            cls._directory.cleanup()

    def setUp(self):
        network.invalidate_network_cache()

    def test_discover_by_topic_inserts_unique_authors(self):
        openalex_item = {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.0/live-one",
            "title": "Nuevo estudio en vivo sobre desinformacion",
            "publication_date": "2026-08-01",
            "authorships": [
                {"author": {"display_name": "Nueva Una", "orcid": "https://orcid.org/0000-0002-1825-0098"}},
                {"author": {"display_name": "Existente Uno", "orcid": None}},
            ],
            "primary_location": {
                "source": {"display_name": "Revista en vivo", "issn": ["1234-5678"]},
                "is_oa": True,
            },
            "open_access": {"is_oa": True},
            "cited_by_count": 2,
            "keywords": [{"display_name": "Misinformation", "score": 0.8}],
            "referenced_works": [],
        }
        crossref_item = {
            "DOI": "10.0/live-two",
            "title": ["Segundo estudio en vivo sobre desinformacion"],
            "author": [{"given": "Segunda", "family": "Dos"}],
            "container-title": ["Segunda revista en vivo"],
            "issued": {"date-parts": [[2026, 7, 1]]},
            "URL": "https://doi.org/10.0/live-two",
            "ISSN": ["2345-6789"],
            "subject": ["desinformacion"],
            "license": [{}],
            "is-referenced-by-count": 3,
        }

        def handler(request):
            if request.url.host == "api.openalex.org":
                return httpx.Response(200, json={"results": [openalex_item]})
            if request.url.host == "api.crossref.org":
                return httpx.Response(200, json={"message": {"items": [crossref_item]}})
            return httpx.Response(404, json={})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            result = live_search.discover_by_topic(self.conn, "desinformacion", days=30, max_results=10, http=client)
        finally:
            client.close()

        self.assertEqual(result["found"], 2)
        self.assertEqual(result["new"], 2)
        self.assertEqual(result["authors_added"], 2)
        self.assertEqual(result["journals_added"], 2)
        self.assertEqual(result["sources"]["openalex"]["new"], 1)
        self.assertEqual(result["sources"]["crossref"]["new"], 1)
        self.assertEqual(db.count_articles(self.conn), 3)
        self.assertEqual(db.count_journals(self.conn), 2)


class RadarDiscoverEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from radar.api import main as api_main

        cls._directory = tempfile.TemporaryDirectory(prefix="thinkuy-api-test-")
        cls._previous_db = config.DB_PATH
        config.DB_PATH = Path(cls._directory.name) / "radar-api-test.db"
        cls._TestClient = TestClient
        cls._api_main = api_main

    @classmethod
    def tearDownClass(cls):
        config.DB_PATH = cls._previous_db
        cls._directory.cleanup()

    def setUp(self):
        network.invalidate_network_cache()
        conn = db.connect()
        db.init_db(conn)
        conn.execute("DELETE FROM watch_keywords")
        conn.commit()
        conn.close()

    def test_discover_validates_payload_and_creates_watch(self):
        with patch.object(
            self._api_main.live_search,
            "discover_by_topic",
            return_value={"found": 1, "new": 1, "authors_added": 1, "sources": {}},
        ), self._TestClient(self._api_main.app) as client:
            response = client.post("/api/radar/discover", json={
                "topic": "Redes Sociales",
                "days": "no-numerico",
                "max_results": 500,
                "limit": 500,
                "min_works": 500,
                "excluded": "uno, dos",
                "included": ["tres"],
            })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["discovery"]["new"], 1)
        self.assertIn("continuous_monitoring", payload)
        self.assertIn("watch", payload["continuous_monitoring"])

        conn = db.connect()
        try:
            watches = db.watch_list(conn)
        finally:
            conn.close()
        self.assertTrue(any(watch["label"].startswith("Radar en vivo:") for watch in watches))

    def test_discover_requires_topic(self):
        with self._TestClient(self._api_main.app) as client:
            response = client.post("/api/radar/discover", json={})
        self.assertEqual(response.status_code, 400)


class ArticleDisplayKeywordsTest(unittest.TestCase):
    def test_declared_keywords_are_preserved(self):
        article = {
            "title": "Artículo de prueba",
            "abstract": "",
            "keywords": ["Primera Palabra", "segunda palabra"],
            "authors": [],
            "journal_title": "Revista de prueba",
        }
        keywords, source = topics.display_keywords(article, limit=5)
        self.assertEqual(keywords, ["Primera Palabra", "segunda palabra"])
        self.assertEqual(source, "declared")

    def test_missing_keywords_are_derived_transparently(self):
        article = {
            "title": "O ciclo da desinformação em plataformas digitais: criação, disseminação e recirculação",
            "abstract": "Algoritmos de recomendação e práticas culturais de compartilhamento moldam circuitos comunicacionais digitais.",
            "keywords": [],
            "authors": [{"given": "Thiago Henrique", "family": "de Jesus-Silva"}],
            "journal_title": "Em Questão",
        }
        keywords, source = topics.display_keywords(article, candidate_terms=["desinformación"], limit=5)
        normalized = {topics.norm(keyword) for keyword in keywords}
        self.assertEqual(source, "derived")
        self.assertTrue(keywords)
        self.assertTrue({"desinformacion", "desinformacao"} & normalized)
        self.assertNotIn("questao", normalized)
        self.assertNotIn("jesus", normalized)
        self.assertNotIn("silva", normalized)


class RadarWatchEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from radar.api import main as api_main

        cls._directory = tempfile.TemporaryDirectory(prefix="thinkuy-watch-test-")
        cls._previous_db = config.DB_PATH
        config.DB_PATH = Path(cls._directory.name) / "radar-watch-test.db"
        cls._TestClient = TestClient
        cls._api_main = api_main

    @classmethod
    def tearDownClass(cls):
        config.DB_PATH = cls._previous_db
        cls._directory.cleanup()

    def setUp(self):
        network.invalidate_network_cache()
        conn = db.connect()
        db.init_db(conn)
        conn.execute("DELETE FROM watch_keywords")
        conn.commit()
        conn.close()

    def test_create_watch_from_keywords(self):
        with self._TestClient(self._api_main.app) as client:
            response = client.post("/api/watch", json={
                "keywords": "desinformacion, redes sociales",
                "label": "Radar: prueba",
            })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["label"], "Radar: prueba")
        self.assertEqual(payload["keywords"], "desinformacion, redes sociales")

    def test_create_watch_requires_keywords(self):
        with self._TestClient(self._api_main.app) as client:
            response = client.post("/api/watch", json={"keywords": "   "})
        self.assertEqual(response.status_code, 422)

    def test_article_endpoint_supplies_derived_display_keywords(self):
        conn = db.connect()
        db.init_db(conn)
        db.upsert_article(conn, {
            "title": "O ciclo da desinformação em plataformas digitais",
            "abstract": "Algoritmos de recomendação moldam circuitos comunicacionais digitais.",
            "keywords": [],
            "authors": [{"given": "Prueba", "family": "Caso"}],
            "journal_title": "Revista de prueba",
            "year": 2026,
            "pub_date": "2026-01-15",
            "source": "test",
            "doi": "10.0/display-keywords",
        })
        conn.close()
        with self._TestClient(self._api_main.app) as client:
            response = client.get("/api/articles/10.0/display-keywords")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["keywords"], [])
        self.assertTrue(payload["display_keywords"])
        self.assertEqual(payload["keyword_source"], "derived")

    def test_radar_work_uses_fallback_keywords(self):
        conn = db.connect()
        db.init_db(conn)
        db.upsert_article(conn, {
            "title": "Estudio de caso sobre desinformación",
            "abstract": "Algoritmos de recomendação moldam circuitos digitais.",
            "keywords": [],
            "authors": [{"given": "Respaldo", "family": "Persona"}],
            "journal_title": "Revista de prueba",
            "year": 2026,
            "pub_date": "2026-01-15",
            "source": "test",
            "doi": "10.0/fallback-radar",
        })
        try:
            network.invalidate_network_cache()
            result = proximity.radar(conn, topic="desinformación", limit=20)
        finally:
            conn.close()
        node = next(
            (item for item in result["nodes"] if item["name"] == "Respaldo Persona"),
            None,
        )
        self.assertIsNotNone(node)
        self.assertTrue(node["works_list"])
        self.assertTrue(node["works_list"][0]["keywords"])
        self.assertEqual(node["works_list"][0]["keyword_source"], "derived")
        self.assertTrue(node["top_keywords"])

    def test_watch_matches_only_selected_subset(self):
        conn = db.connect()
        db.init_db(conn)
        conn.execute("DELETE FROM watch_keywords")
        conn.execute("DELETE FROM articles")
        conn.commit()
        anchor = db.watch_create(conn, "B, D", "Radar: prueba granular")
        db.upsert_article(conn, {
            "title": "Artículo de prueba uno",
            "abstract": "",
            "keywords": ["B", "D", "E"],
            "authors": [],
            "journal_title": "Revista de prueba",
            "year": 2026,
            "pub_date": "2026-01-15",
            "source": "test",
            "doi": "10.0/granular-bde",
        })
        db.upsert_article(conn, {
            "title": "Artículo de prueba dos",
            "abstract": "",
            "keywords": ["C", "E"],
            "authors": [],
            "journal_title": "Revista de prueba",
            "year": 2026,
            "pub_date": "2026-01-15",
            "source": "test",
            "doi": "10.0/granular-ce",
        })
        try:
            results = db.watch_new_articles(conn, anchor)
        finally:
            conn.close()
        self.assertEqual([article["doi"] for article in results], ["10.0/granular-bde"])


if __name__ == "__main__":
    unittest.main()
