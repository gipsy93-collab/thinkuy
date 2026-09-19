"""Etapa 2: migración, CRUD de validación, clasificador IA (simulado), XML y DOIs."""
import json
import sqlite3
import sys

sys.path.insert(0, ".")

from backend.radar import db as dbmod
from backend.radar import librarian, text_extractor


def memdb():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    dbmod.init_db(conn)
    return conn


def test_migration_columns():
    conn = memdb()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(citation_contexts)").fetchall()}
    for c in ("claim_text", "confidence", "validation_status", "validated_by", "validated_at"):
        assert c in cols, c
    conn.close()


def test_save_get_validate():
    conn = memdb()
    cid = dbmod.save_citation_context(conn, "10.aaa/1", "10.bbb/2", {
        "paragraph": "Como dicen X et al. (2020), el método funciona.",
        "sentence": "Como dicen X et al. (2020), el método funciona.",
        "function": "methodological_adoption",
        "claim": "el método funciona",
        "confidence": "high",
    })
    rows = dbmod.get_citation_contexts(conn, status="pending")
    assert len(rows) == 1 and rows[0]["claim_text"] == "el método funciona"
    assert rows[0]["sentiment"] == "methodological_adoption"
    assert dbmod.get_citation_contexts(conn, status="validated") == []

    upd = dbmod.validate_citation_context(conn, cid, "corrected",
                                          corrected_function="supporting_or_agreement",
                                          corrected_claim="funciona bien", by="tester")
    assert upd["sentiment"] == "supporting_or_agreement"
    assert upd["claim_text"] == "funciona bien"
    assert upd["validation_status"] == "corrected" and upd["validated_by"] == "tester"

    upd2 = dbmod.validate_citation_context(conn, cid, "validated")
    assert upd2["validation_status"] == "validated"

    try:
        dbmod.validate_citation_context(conn, cid, "bogus")
        raise AssertionError("debió fallar")
    except ValueError:
        pass
    assert dbmod.validate_citation_context(conn, 99999, "validated") is None
    conn.close()


def _fake_chat_factory(payload):
    def _fake(system, user, temperature=0.1, max_tokens=1000, **kwargs):
        return json.dumps(payload)
    return _fake


def test_classifier_valid_and_verbatim():
    items = [
        {"paragraph": "Torres afirma que las metricas complementan la evaluacion.", "sentence": "x"},
        {"paragraph": "Otro párrafo sin relación con lo afirmado.", "sentence": "y"},
    ]
    librarian._chat = _fake_chat_factory([
        {"idx": 0, "function": "supporting_or_agreement",
         "claim": "las metricas complementan la evaluacion", "confidence": "high"},
        {"idx": 1, "function": "contrasting_or_refuting",
         "claim": "inventado fuera del texto", "confidence": "high"},
    ])
    librarian.available = lambda: True
    out = librarian.classify_citation_functions(items)
    assert out[0]["function"] == "supporting_or_agreement"
    assert out[0]["claim"] == "las metricas complementan la evaluacion"
    assert out[0]["confidence"] == "high"
    # claim no literal -> se descarta pero se conserva la función
    assert out[1]["function"] == "contrasting_or_refuting"
    assert out[1]["claim"] is None and out[1]["confidence"] == "low"


def test_classifier_invalid_function_and_offline():
    items = [{"paragraph": "Párrafo cualquiera.", "sentence": "s"}]
    librarian._chat = _fake_chat_factory([{"idx": 0, "function": "alucinada", "claim": "", "confidence": "high"}])
    librarian.available = lambda: True
    out = librarian.classify_citation_functions(items)
    assert out[0]["function"] is None
    librarian.available = lambda: False
    assert librarian.classify_citation_functions(items) == []


def test_batch_merge_keeps_heuristic():
    import backend.radar.librarian as libmod
    orig = libmod.classify_citation_functions
    libmod.classify_citation_functions = lambda items, batch_size=20: []
    try:
        det = [{"paragraph": "p", "sentence": "s", "sentiment": "neutral_or_mention"}]
        merged = text_extractor.batch_classify_contexts(det)
        assert merged[0]["function"] == "neutral_or_mention"
        assert merged[0]["confidence"] == "heuristic"
    finally:
        libmod.classify_citation_functions = orig


def test_batch_merge_applies_ai():
    import backend.radar.librarian as libmod
    orig = libmod.classify_citation_functions
    libmod.classify_citation_functions = lambda items, batch_size=20: [
        {"function": "methodological_adoption", "claim": "usamos su escala", "confidence": "high"}
    ]
    try:
        det = [{"paragraph": "usamos su escala", "sentence": "s", "sentiment": "neutral_or_mention"}]
        merged = text_extractor.batch_classify_contexts(det)
        assert merged[0]["function"] == "methodological_adoption"
        assert merged[0]["claim"] == "usamos su escala"
        assert merged[0]["confidence"] == "high"
    finally:
        libmod.classify_citation_functions = orig


def test_reference_entries_skipped():
    ref = ("García M. 2020. Título del artículo. Revista X, 58(3), 493-536. "
           "https://doi.org/10.24201/fi.v58i3.2530")
    assert text_extractor._looks_like_reference_entry(ref) is True
    assert text_extractor.extract_citation_contexts(
        ref, cited_doi="10.24201/fi.v58i3.2530") == []
    # Prosa real con DOI crudo: se conserva
    prose = ("Como demuestran Torres-Salinas et al. (2013), ver 10.1002/asi.23056, "
             "las altmétricas complementan la evaluación con evidencia amplia del campo.")
    assert text_extractor._looks_like_reference_entry(prose) is False
    assert len(text_extractor.extract_citation_contexts(prose, cited_doi="10.1002/asi.23056")) == 1


def test_xml_and_dois():
    para = ("<p>Texto introductorio con contenido suficiente para superar el umbral "
            "minimo de palabras del extractor y con cita 10.1234/abc incluida.</p>")
    xml = f"""<article><front><title>A</title></front><body>
    <sec><title>Introduction</title>{para * 4}</sec>
    <sec><title>References</title><p>Smith J. 2020. Revista. https://doi.org/10.5678/xyz,</p>
    <p>Otro sin doi pero con bastantes palabras de relleno para el conteo.</p></sec></body></article>"""
    md = text_extractor.extract_xml_to_markdown(xml)
    assert md and "introduction" in md["sections"] and "references" in md["sections"]
    dois = text_extractor.extract_dois_from_texts(md["references"])
    assert dois == ["10.5678/xyz"], dois
    assert text_extractor.extract_xml_to_markdown("<a><p>corto</p></a>") is None
    assert text_extractor.extract_dois_from_texts(None) == []


def test_fulltext_body_citation_extraction():
    conn = memdb()
    full_text = """## Introduction
La deliberación democrática contemporánea está mediada por arquitecturas algorítmicas.
Como argumenta Habermas (1989), la esfera pública exige condiciones ideales de simetría discursiva para validar el consenso racional entre los participantes.

## Discussion
Sin embargo, en el ecosistema digital contemporáneo esto se complica.
Por otra parte, Castells (2009) demuestra que el poder de la comunicación reside hoy en la capacidad de programar redes digitales globales. Esto contradice las visiones tecno-optimistas ingenuas.

## References
Habermas, J. (1989). The Structural Transformation of the Public Sphere. MIT Press.
Castells, M. (2009). Communication Power. Oxford University Press. https://doi.org/10.1093/acprof:oso/9780199567706.001.0001
"""
    sections = {
        "introduction": "La deliberación democrática contemporánea está mediada por arquitecturas algorítmicas.\nComo argumenta Habermas (1989), la esfera pública exige condiciones ideales de simetría discursiva para validar el consenso racional entre los participantes.",
        "discussion": "Sin embargo, en el ecosistema digital contemporáneo esto se complica.\nPor otra parte, Castells (2009) demuestra que el poder de la comunicación reside hoy en la capacidad de programar redes digitales globales. Esto contradice las visiones tecno-optimistas ingenuas.",
        "references": "Habermas, J. (1989). The Structural Transformation of the Public Sphere. MIT Press.\nCastells, M. (2009). Communication Power. Oxford University Press. https://doi.org/10.1093/acprof:oso/9780199567706.001.0001",
    }
    refs_texts = [
        "Habermas, J. (1989). The Structural Transformation of the Public Sphere. MIT Press.",
        "Castells, M. (2009). Communication Power. Oxford University Press. https://doi.org/10.1093/acprof:oso/9780199567706.001.0001",
    ]

    res = text_extractor.ingest_fulltext_and_contexts(
        conn,
        citing_doi="10.test/paper2026",
        full_text=full_text,
        sections=sections,
        references_texts=refs_texts,
        auto_ingest_refs=False,  # No red en test unitario
    )

    assert res["citation_contexts_extracted"] >= 2, f"Extrajo {res['citation_contexts_extracted']} contextos"
    
    # Comprobar que extrajo los párrafos del cuerpo reales
    paras = [c["paragraph"] for c in res["contexts"]]
    assert any("Habermas" in p and "simetría discursiva" in p for p in paras)
    assert any("Castells" in p and "programar redes" in p for p in paras)
    
    # Comprobar que extrajo las oraciones y claims literales
    claims = [c["claim"] for c in res["contexts"]]
    assert any("simetría discursiva" in cl for cl in claims)
    assert any("programar redes" in cl for cl in claims)
    
    # Comprobar persistencia en SQLite
    stored = dbmod.get_citation_contexts(conn, citing_doi="10.test/paper2026")
    assert len(stored) >= 2
    conn.close()


if __name__ == "__main__":
    test_migration_columns()
    print("migration OK")
    test_save_get_validate()
    print("crud validación OK")
    test_classifier_valid_and_verbatim()
    print("clasificador OK")
    test_classifier_invalid_function_and_offline()
    print("fallback OK")
    test_batch_merge_keeps_heuristic()
    test_batch_merge_applies_ai()
    print("merge OK")
    test_reference_entries_skipped()
    print("refentries OK")
    test_xml_and_dois()
    print("xml+dois OK")
    test_fulltext_body_citation_extraction()
    print("body citation extraction OK")
    print("TODOS LOS TESTS OK")
