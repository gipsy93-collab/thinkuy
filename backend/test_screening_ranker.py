"""Pruebas unitarias para el motor de Active Learning Incremental (screening_ranker.py)."""
from radar.screening_ranker import ScreeningActiveLearner, compute_screening_progress_metrics


def test_active_learner_prioritizes_similar_articles():
    corpus = [
        {
            "doi": "10.1001/disinfo.1",
            "title": "Desinformación y fake news en redes sociales digitales",
            "abstract": "Análisis de la difusión de noticias falsas y desinformación durante elecciones.",
            "keywords": ["desinformacion", "fake news", "redes sociales"],
        },
        {
            "doi": "10.1001/disinfo.2",
            "title": "Verificación y fact-checking periodístico frente a bulos",
            "abstract": "Estrategias de verificación de datos para combatir la desinformación en medios.",
            "keywords": ["fact-checking", "verificacion", "desinformacion"],
        },
        {
            "doi": "10.1001/unrelated.1",
            "title": "Estudio espectroscópico de supernovas en galaxias lejanas",
            "abstract": "Observación astrofísica de emisiones estelares mediante telescopios espaciales.",
            "keywords": ["astrofisica", "supernovas", "galaxia"],
        },
        {
            "doi": "10.1001/unrelated.2",
            "title": "Dinámica de sedimentos costeros y erosión marina",
            "abstract": "Evaluación geomorfológica del transporte litoral de arenas en playas atlánticas.",
            "keywords": ["geologia", "costas", "sedimentos"],
        },
    ]

    learner = ScreeningActiveLearner()
    learner.fit_corpus(corpus)

    # El investigador incluye el primer artículo sobre desinformación
    decisions = {
        "10.1001/disinfo.1": "included",
    }

    ranked = learner.rank_candidates(corpus, decisions)
    assert len(ranked) == 4

    # El primer candidato pendiente sugerido DEBE ser el artículo 2 (fact-checking y desinformación)
    pending = [r for r in ranked if r["decision"] == "pending"]
    assert len(pending) == 3
    assert pending[0]["article"]["doi"] == "10.1001/disinfo.2"
    assert pending[0]["priority_score"] > pending[1]["priority_score"]
    assert len(pending[0]["explanation_terms"]) > 0
    assert any("desinformacion" in term for term in pending[0]["explanation_terms"])


def test_active_learner_repels_excluded_articles():
    corpus = [
        {
            "doi": "10.1001/pol.1",
            "title": "Comunicación política en campañas electorales televisadas",
            "abstract": "Debates electorales y framing en televisión pública.",
        },
        {
            "doi": "10.1001/pol.2",
            "title": "Estrategias de propaganda y marketing electoral televisivo",
            "abstract": "Spots publicitarios en televisión y polarización partidista.",
        },
        {
            "doi": "10.1001/med.1",
            "title": "Comunicación científica en salud pública y vacunas",
            "abstract": "Divulgación de evidencia médica en crisis sanitarias.",
        },
    ]

    learner = ScreeningActiveLearner(alpha=1.0, beta=0.8)
    learner.fit_corpus(corpus)

    # Si se excluye el tema de marketing electoral televisivo
    decisions = {
        "10.1001/med.1": "included",
        "10.1001/pol.2": "excluded",
    }

    ranked = learner.rank_candidates(corpus, decisions)
    pending = [r for r in ranked if r["decision"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["article"]["doi"] == "10.1001/pol.1"
    # Al estar polarizado con el excluido (televisión, electoral), su score recibe penalización
    assert pending[0]["priority_score"] < 0.2


def test_progress_metrics():
    screenings = [
        {"doi": "doi1", "decision": "included"},
        {"doi": "doi2", "decision": "excluded"},
        {"doi": "doi3", "decision": "included"},
        {"doi": "doi4", "decision": "maybe"},
    ]
    metrics = compute_screening_progress_metrics(10, screenings)
    assert metrics["total_corpus"] == 10
    assert metrics["screened"] == 4
    assert metrics["remaining"] == 6
    assert metrics["included"] == 2
    assert metrics["excluded"] == 1
    assert metrics["maybe"] == 1
    assert metrics["pct_screened"] == 40.0
    assert metrics["has_active_learning"] is True


def test_active_learning_endpoint():
    from fastapi.testclient import TestClient
    from radar import db
    from radar.api.main import app

    conn = db.connect()
    db.init_db(conn)  # el servidor migra al arrancar; aquí se hace explícito
    pid = None
    try:
        pid = db.save_protocol(
            conn,
            {
                "title": "Protocolo Test Active Learning",
                "research_question": "¿Cómo influye la desinformación en elecciones?",
            },
        )
        # Registrar una decisión
        db.save_screening(conn, pid, doi="10.1001/disinfo.1", decision="included", screened_by="test")

        client = TestClient(app)
        payload = {
            "articles": [
                {
                    "doi": "10.1001/disinfo.1",
                    "title": "Desinformación y fake news en redes",
                    "abstract": "Estudio de noticias falsas.",
                },
                {
                    "doi": "10.1001/disinfo.2",
                    "title": "Verificación de bulos y desinformación digital",
                    "abstract": "Fact-checking en redes.",
                },
                {
                    "doi": "10.1001/chem.1",
                    "title": "Síntesis catalítica de polímeros",
                    "abstract": "Química macromolecular.",
                },
            ]
        }
        resp = client.post(f"/api/review/protocol/{pid}/screening/rank", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["protocol_id"] == pid
        assert data["metrics"]["included"] == 1
        assert len(data["candidates"]) == 3
        # El primer candidato pendiente sugerido debe ser el de verificación de desinformación
        pending = [c for c in data["candidates"] if c["decision"] == "pending"]
        assert pending[0]["article"]["doi"] == "10.1001/disinfo.2"
    finally:
        if pid is not None:
            conn.execute("DELETE FROM article_screenings WHERE protocol_id = ?", (pid,))
            conn.execute("DELETE FROM review_protocols WHERE id = ?", (pid,))
            conn.commit()
        conn.close()

