"""Pruebas unitarias de matching y normalización para Thinkuy."""
import unittest
from radar.normalize import norm, norm_lang, word_variants, edit_distance
from radar.matching import match_article, parse_keywords, rank_articles


class TestNormalize(unittest.TestCase):
    def test_norm_strips_accents_and_lowercases(self):
        self.assertEqual(norm("Comunicación Política"), "comunicacion politica")
        self.assertEqual(norm("DESINFORMACIÓN y Fake-News!"), "desinformacion y fake news")

    def test_norm_lang(self):
        self.assertEqual(norm_lang("spa"), "es")
        self.assertEqual(norm_lang("es-ES"), "es")
        self.assertEqual(norm_lang("por"), "pt")
        self.assertEqual(norm_lang("pt-BR"), "pt")
        self.assertEqual(norm_lang("eng"), "en")
        self.assertIsNone(norm_lang("unknown"))

    def test_word_variants_es_pt(self):
        vars_es = word_variants("comunicacion")
        self.assertIn("comunicacao", vars_es)
        self.assertIn("comunicaciones", vars_es)

        vars_soc = word_variants("social")
        self.assertIn("sociais", vars_soc)
        self.assertIn("sociales", vars_soc)

    def test_edit_distance(self):
        self.assertEqual(edit_distance("comunicacion", "comunicacion"), 0)
        self.assertEqual(edit_distance("comunciacion", "comunicacion"), 1)  # transposición


class TestMatching(unittest.TestCase):
    def test_parse_keywords(self):
        raw = "comunicación política, desinformación; medios digitales - redes sociales"
        kws = parse_keywords(raw)
        self.assertEqual(len(kws), 4)
        self.assertIn("comunicación política", kws)
        self.assertIn("desinformación", kws)
        self.assertIn("medios digitales", kws)
        self.assertIn("redes sociales", kws)

    def test_exact_phrase_match_higher_than_token_match(self):
        article_phrase = {
            "title": "Un estudio sobre comunicación política en elecciones",
            "abstract": "Análisis electoral.",
            "keywords": ["elecciones", "democracia"],
        }
        article_single = {
            "title": "La comunicación y la teoría política",
            "abstract": "Conceptos teóricos.",
            "keywords": ["teoría"],
        }
        score_phrase = match_article(article_phrase, ["comunicación política"])["score"]
        score_single = match_article(article_single, ["comunicación política"])["score"]

        self.assertGreater(score_phrase, score_single)
        self.assertGreater(score_phrase, 0)

    def test_pt_es_cross_matching(self):
        article_pt = {
            "title": "A desinformação nas redes sociais digitais",
            "abstract": "Estudo empírico.",
            "keywords": ["redes sociais", "jornalismo"],
        }
        # Buscar en español
        res = match_article(article_pt, ["desinformación"])
        self.assertGreater(res["score"], 0)


class TestScientificMatching(unittest.TestCase):
    def setUp(self):
        import sqlite3
        from radar import db
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(db._SCHEMA)
        
        # Insertar revistas de prueba
        self.conn.execute("INSERT INTO journals (title, issn_online, country) VALUES (?, ?, ?)",
                          ("Revista Mediterránea de Comunicación", "1989-872X", "ES"))
        self.conn.execute("INSERT INTO journals (title, issn_online, country) VALUES (?, ?, ?)",
                          ("Comunicar", "1988-3293", "ES"))

        # Insertar artículos de prueba
        self.conn.execute("""
            INSERT INTO articles (doi, title, abstract, keywords, authors, journal_title, year, pub_date, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "10.1234/test1",
            "Desinformación y fake news en campañas electorales",
            "Estudio empírico sobre redes sociales y polarización.",
            '["desinformación", "elecciones", "redes sociales"]',
            '[{"given": "Ana", "family": "García", "orcid": "0000-0001-1111-2222"}, {"given": "Carlos", "family": "Pérez"}]',
            "Revista Mediterránea de Comunicación",
            2024,
            "2024-05-10",
            "crossref"
        ))

        self.conn.execute("""
            INSERT INTO articles (doi, title, abstract, keywords, authors, journal_title, year, pub_date, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "10.1234/test2",
            "Alfabetización mediática contra la desinformación digital",
            "Estrategias pedagógicas para combatir bulos.",
            '["alfabetización mediática", "desinformación", "educación"]',
            '[{"given": "María", "family": "López", "orcid": "0000-0002-3333-4444"}]',
            "Comunicar",
            2025,
            "2025-01-15",
            "crossref"
        ))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_journal_matching_by_topic(self):
        from radar.author_match import find_journal_matches
        res = find_journal_matches(self.conn, topic_query="desinformación en elecciones", limit=5)
        self.assertEqual(res["status"], "ok")
        self.assertGreater(res["count"], 0)
        top_match = res["matches"][0]
        self.assertIn("desinformacion", [norm(c) for c in top_match["shared_concepts"]])
        self.assertGreaterEqual(top_match["fidelity"], 60)

    def test_reviewer_matching_and_conflict_exclusion(self):
        from radar.author_match import find_reviewer_matches
        
        # Caso 1: Búsqueda libre -> sugiere a Ana García y María López
        res = find_reviewer_matches(self.conn, topic_query="desinformación", limit=5)
        self.assertEqual(res["status"], "ok")
        names = [m["name"] for m in res["matches"]]
        self.assertTrue(any("García" in n or "López" in n for n in names))

        # Caso 2: Manuscrito del autor "Ana García" -> Ana García y su coautor Carlos Pérez deben ser excluidos por COI
        res_coi = find_reviewer_matches(self.conn, author_name="Ana García", topic_query="desinformación", limit=5)
        names_coi = [m["name"] for m in res_coi["matches"]]
        self.assertNotIn("Ana García", names_coi)
        self.assertNotIn("Carlos Pérez", names_coi)
        # María López no tiene conflicto, debe ser sugerida
        self.assertTrue(any("López" in n for n in names_coi))
        self.assertIn("ojs_slip", res_coi["matches"][0])


if __name__ == "__main__":
    unittest.main()
