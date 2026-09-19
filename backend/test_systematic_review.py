"""Agente A.1 Metodólogo: prompt preservado, grounding en corpus, fallback, endpoint."""
import sqlite3
import sys

sys.path.insert(0, ".")

from backend.radar import db as dbmod
from backend.radar import librarian


def test_prompt_preserved():
    s = librarian._METHODOLOGIST_SYSTEM
    for key in ("PICOS", "TITLE-ABS-KEY", "30 y 300", "Declaración de uso de IA",
                "ESPAÑOL", "Cero Alucinaciones", "PRISMA"):
        assert key in s, key


def test_grounded_and_fallbacks():
    corpus = [
        {"doi": "10.aaa/1", "title": "Altmetrics en salud", "year": 2021,
         "journal_title": "J", "abstract": "Resumen uno."},
        {"doi": "10.bbb/2", "title": "Sin abstract", "year": 2020,
         "journal_title": "K", "abstract": ""},
    ]
    seen = {}

    def fake_chat(system, user, temperature=0.2, max_tokens=3000, **kw):
        seen["system"] = system
        seen["user"] = user
        return "INFORME SIMULADO"

    librarian._chat = fake_chat
    librarian.available = lambda: True
    res = librarian.run_systematic_review("altmetrics en salud", corpus)
    assert res["status"] == "ok" and res["corpus_count"] == 2
    assert res["report"] == "INFORME SIMULADO"
    assert "10.aaa/1" in seen["user"] and "Altmetrics en salud" in seen["user"]
    assert "PRISMA" in seen["system"]

    assert librarian.run_systematic_review("x", [])["status"] == "empty"
    assert librarian.run_systematic_review("x", [{"title": "sin doi"}])["status"] == "empty"
    librarian.available = lambda: False
    r = librarian.run_systematic_review("x", corpus)
    assert r["status"] == "no_llm" and r["corpus_count"] == 2


def _seeded_mem(n_extra: int = 0):
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    dbmod.init_db(mem)
    mem.execute(
        "INSERT INTO articles (doi, title, abstract, source) VALUES (?, ?, ?, 'test')",
        ("10.ccc/3", "Altmetrics y comunicación científica", "Estudio sobre altmetrics."),
    )
    for i in range(n_extra):
        mem.execute(
            "INSERT INTO articles (doi, title, abstract, source) VALUES (?, ?, ?, 'test')",
            (f"10.t{i}/x", f"Altmetrics estudio número {i}", "Altmetrics resumen."),
        )
    mem.commit()
    return mem


def test_endpoint_boolean_and_sample_gate():
    from backend.radar.api import main as api_main

    orig_chat, orig_avail = librarian._chat, librarian.available
    seen = {}
    librarian._chat = lambda s, u, temperature=0.2, max_tokens=3000, **k: (seen.update(user=u), "REPORTE")[1]
    librarian.available = lambda: True
    try:
        api_main.db.connect = lambda *a, **k: _seeded_mem()
        out = api_main.systematic_review_endpoint({
            "inquiry": "lo que sea",
            "boolean_query": '("altmetrics") AND ("comunicación")',
        })
        assert out["boolean_logic"] == '("altmetrics") AND ("comunicación")', out
        assert any(a["doi"] == "10.ccc/3" for a in out["corpus"]), out["corpus"]
        assert out["sample_status"] == "narrow" and "específico" in out["sample_message"], out
        assert "Rango óptimo" in seen["user"]

        api_main.db.connect = lambda *a, **k: _seeded_mem(n_extra=310)
        out2 = api_main.systematic_review_endpoint({"inquiry": "altmetrics", "limit": 100})
        assert out2["sample_status"] == "broad" and out2["total_found"] == 311, out2
        assert out2["audit"]["rows_checked"] == 0 and out2["audit"]["clean"] is True
    finally:
        api_main.db.connect = dbmod.connect
        librarian._chat = orig_chat
        librarian.available = orig_avail


def test_parse_boolean_query():
    from backend.radar.matching import parse_boolean_query
    p = parse_boolean_query('("diabetes" OR "t2dm") AND ("exercise" OR "physical activity")')
    assert p["keywords"] == ["diabetes", "t2dm", "exercise", "physical activity"], p
    assert "AND" in p["boolean_logic"] and "OR" in p["boolean_logic"]
    p2 = parse_boolean_query("altmetrics redes sociales NOT tiktok")
    assert "tiktok" in p2["keywords"] and "NOT" not in p2["keywords"], p2
    assert parse_boolean_query("") == {"keywords": [], "boolean_logic": ""}
    assert parse_boolean_query(None) == {"keywords": [], "boolean_logic": ""}


def test_audit_extraction():
    corpus = [
        {"doi": "10.aaa/1", "title": "Altmetrics en salud pública"},
        {"doi": "10.bbb/2", "title": "Comunicación científica digital"},
    ]
    report = (
        "| Título | Descripción | Año | Muestra | Metodología | Resultados | Conclusiones |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Altmetrics en salud pública | Síntesis breve | 2021 | N=10 | Encuesta | Clave | Fin |\n"
        "| Estudio inventado que no existe | Otra síntesis | 2022 | N=5 | Caso | Nada | Fin |\n"
        "Ver también 10.9999/ajeno.\n"
    )
    a = librarian.audit_extraction(report, corpus)
    assert a["rows_checked"] == 2, a
    assert len(a["unmatched"]) == 1 and "inventado" in a["unmatched"][0]["title"], a
    assert a["foreign_dois"] == ["10.9999/ajeno"], a
    assert a["clean"] is False
    clean = librarian.audit_extraction(
        "| Título | Descripción | Año |\n"
        "| Altmetrics en salud pública | Síntesis breve | 2021 |", corpus)
    assert clean["clean"] is True and clean["rows_checked"] == 1, clean


def test_endpoint_with_memory_db():
    from backend.radar.api import main as api_main

    orig_connect, orig_chat, orig_avail = dbmod.connect, librarian._chat, librarian.available
    librarian._chat = lambda s, u, temperature=0.2, max_tokens=3000, **k: "REPORTE E2E"
    librarian.available = lambda: True
    try:
        # api.main importó `db` por referencia: parchear el atributo usado
        api_main.db.connect = lambda *a, **k: _seeded_mem()
        out = api_main.systematic_review_endpoint({"inquiry": "altmetrics", "limit": 10})
        assert out["inquiry"] == "altmetrics"
        assert out["status"] == "ok" and out["report"] == "REPORTE E2E"
        assert any(a["doi"] == "10.ccc/3" for a in out["corpus"]), out["corpus"]

        out2 = api_main.systematic_review_endpoint(
            {"inquiry": "altmetrics", "dois": ["10.ccc/3", "10.zzz/no-existe"]})
        assert out2["corpus_count"] == 1

        try:
            api_main.systematic_review_endpoint({"inquiry": "  "})
            raise AssertionError("debió fallar 422")
        except Exception as e:
            assert getattr(e, "status_code", None) == 422, e
    finally:
        dbmod.connect = orig_connect
        api_main.db.connect = orig_connect
        librarian._chat = orig_chat
        librarian.available = orig_avail


if __name__ == "__main__":
    test_prompt_preserved()
    print("prompt OK")
    test_grounded_and_fallbacks()
    print("grounding OK")
    test_endpoint_with_memory_db()
    print("endpoint OK")
    test_parse_boolean_query()
    print("booleano OK")
    test_audit_extraction()
    print("auditoría OK")
    test_endpoint_boolean_and_sample_gate()
    print("gate 30-300 OK")
    print("TODOS LOS TESTS A.1 OK")
