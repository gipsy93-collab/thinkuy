"""Pruebas unitarias de los parámetros ajustables del algoritmo de proximidad del radar."""
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from radar import config, db, network, proximity
from radar.api.main import app


def make_article(title, doi, authors, year=2026, abstract="Estudio sobre desinformacion y medios", journal="Revista de Comunicacion"):
    return {
        "title": title,
        "abstract": abstract,
        "keywords": ["desinformacion", "redes sociales"],
        "authors": authors,
        "journal_title": journal,
        "year": year,
        "pub_date": f"{year}-01-15",
        "lang": "es",
        "url": f"https://doi.org/{doi}",
        "source": "test",
        "source_id": doi,
        "doi": doi,
    }


class ProximityParamsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory(prefix="thinkuy-proximity-test-")
        cls._previous_db = config.DB_PATH
        config.DB_PATH = Path(cls._directory.name) / "proximity-test.db"
        cls.conn = db.connect()
        db.init_db(cls.conn)

        # Crear artículos con varios autores, años y coautorías
        db.upsert_article(cls.conn, make_article(
            "Desinformacion y polarizacion en redes",
            "10.0/test-1",
            [{"given": "Ana", "family": "Torres"}, {"given": "Bruno", "family": "Lima"}],
            year=2026,
            journal="Revista A",
        ))
        db.upsert_article(cls.conn, make_article(
            "Impacto de la desinformacion en campanas",
            "10.0/test-2",
            [{"given": "Ana", "family": "Torres"}, {"given": "Carlos", "family": "Vega"}],
            year=2025,
            journal="Revista A",
        ))
        db.upsert_article(cls.conn, make_article(
            "Medios digitales y alfabetizacion informativa",
            "10.0/test-3",
            [{"given": "Diana", "family": "Solo"}],
            year=2021,
            journal="Revista B",
        ))
        db.upsert_article(cls.conn, make_article(
            "Estudio historico de propaganda",
            "10.0/test-4",
            [{"given": "Eduardo", "family": "Rios"}],
            year=2018,
            journal="Revista C",
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

    def test_affinity_divisor_scales_proximity(self):
        """Un divisor de afinidad menor incrementa el peso de afinidad para scores de matching positivos."""
        res_low_div = proximity.radar(self.conn, topic="desinformacion", affinity_divisor=20, limit=10)
        res_high_div = proximity.radar(self.conn, topic="desinformacion", affinity_divisor=120, limit=10)

        prox_map_low = {n["id"]: n["proximity"] for n in res_low_div["nodes"]}
        prox_map_high = {n["id"]: n["proximity"] for n in res_high_div["nodes"]}

        # Para autores con obras afines al tema, prox_low >= prox_high
        for author_id in prox_map_low:
            if author_id in prox_map_high:
                self.assertGreaterEqual(prox_map_low[author_id], prox_map_high[author_id])

    def test_recency_decay_modes(self):
        """Ambos modos de recencia (linear y exponential) computan valores validos y deterministas."""
        res_lin = proximity.radar(self.conn, topic="desinformacion", recency_decay="linear", limit=10)
        res_exp = proximity.radar(self.conn, topic="desinformacion", recency_decay="exponential", limit=10)

        self.assertGreater(len(res_lin["nodes"]), 0)
        self.assertGreater(len(res_exp["nodes"]), 0)

        for n in res_lin["nodes"]:
            self.assertFalse(any(v is None for v in (n["x"], n["y"], n["proximity"])))
        for n in res_exp["nodes"]:
            self.assertFalse(any(v is None for v in (n["x"], n["y"], n["proximity"])))

    def test_productivity_constant_effect(self):
        """Una constante C menor eleva el factor n/(n+C), aumentando o igualando la proximidad."""
        res_low_c = proximity.radar(self.conn, topic="desinformacion", productivity_constant=1.0, limit=10)
        res_high_c = proximity.radar(self.conn, topic="desinformacion", productivity_constant=20.0, limit=10)

        prox_low = {n["id"]: n["proximity"] for n in res_low_c["nodes"]}
        prox_high = {n["id"]: n["proximity"] for n in res_high_c["nodes"]}

        for aid in prox_low:
            if aid in prox_high:
                self.assertGreaterEqual(prox_low[aid], prox_high[aid])

    def test_normalize_multiplex_weights(self):
        """Cuando normalize_weights=True, todos los pesos de las aristas estan en [0, 1]."""
        res_norm = proximity.radar(self.conn, topic="desinformacion", normalize_weights=True, limit=10)
        for edge in res_norm["edges"]:
            self.assertGreaterEqual(edge["weight"], 0.0)
            self.assertLessEqual(edge["weight"], 1.0001)

    def test_determinism(self):
        """Ejecutar radar con los mismos parametros devuelve exactamente el mismo resultado."""
        res1 = proximity.radar(
            self.conn,
            topic="desinformacion",
            affinity_divisor=45,
            productivity_constant=4.0,
            min_dist=12.0,
            recency_decay="exponential",
            normalize_weights=True,
            limit=5,
        )
        res2 = proximity.radar(
            self.conn,
            topic="desinformacion",
            affinity_divisor=45,
            productivity_constant=4.0,
            min_dist=12.0,
            recency_decay="exponential",
            normalize_weights=True,
            limit=5,
        )

        nodes1 = [(n["id"], n["proximity"], n["x"], n["y"]) for n in res1["nodes"]]
        nodes2 = [(n["id"], n["proximity"], n["x"], n["y"]) for n in res2["nodes"]]
        self.assertEqual(nodes1, nodes2)
        self.assertEqual(res1["edges"], res2["edges"])

    def test_api_endpoint_params(self):
        """El endpoint GET /api/radar responde con 200 al recibir los nuevos parametros."""
        client = TestClient(app)
        resp = client.get("/api/radar", params={
            "topic": "desinformacion",
            "affinity_divisor": 50,
            "productivity_constant": 3.5,
            "min_dist": 15.0,
            "recency_decay": "exponential",
            "normalize_weights": True,
            "limit": 10,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        self.assertIn("weights", data)
