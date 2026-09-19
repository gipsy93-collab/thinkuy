"""Pruebas de la escalera de relajación de la sonda en vivo.

Motivo (medido el 18-09-2026): OpenAlex trata el `search` como conjunción de todos los
términos, así que una pregunta larga devuelve cero. La sonda ahora reintenta relajando y
declara con qué consulta encontró.
"""
from unittest.mock import patch

from radar.harvester import live_probe

# Pregunta real de un investigador (la que devolvió cero artículos).
PREGUNTA = ("Qué instrumentos o escala se utiliza para valorar un paciente con antecedes "
            "de cáncer de riñón y miocarditis para evaluar la percepción manejo de la salud")
PALABRAS = ["Qué instrumentos o escala se utiliza", "valorar un paciente", "antecedes",
            "cáncer", "riñón y miocarditis", "evaluar la percepción manejo"]


# ── La escalera (función pura) ──────────────────────────────────────────────

def test_primer_escalon_es_la_consulta_estricta():
    escalera = live_probe.escalera_de_consultas("comunicación política", ["comunicación política"])

    assert escalera[0] == "comunicación política"


def test_la_escalera_se_relaja_progresivamente():
    escalera = live_probe.escalera_de_consultas(PREGUNTA, PALABRAS)

    assert len(escalera) >= 2
    palabras = [len(escalon.split()) for escalon in escalera]
    assert palabras[0] > palabras[-1], "la escalera debe terminar más relajada que empieza"
    assert min(palabras) <= 2, "debe existir un escalón de uno o dos términos"


def test_la_escalera_no_repite_consultas():
    escalera = live_probe.escalera_de_consultas(PREGUNTA, PALABRAS)

    assert len(escalera) == len(set(escalera))


def test_la_escalera_respeta_el_maximo_de_intentos():
    escalera = live_probe.escalera_de_consultas(PREGUNTA, PALABRAS, maximo=3)

    assert len(escalera) == 3


def test_los_terminos_de_contenido_descartan_el_andamiaje():
    terminos = live_probe._terminos_de_contenido(PREGUNTA)

    # Andamiaje fuera
    for basura in ("qué", "utiliza", "valorar", "evaluar", "para"):
        assert basura not in terminos
    # Núcleo del dominio dentro
    for nucleo in ("instrumentos", "escala", "percepción", "salud"):
        assert nucleo in terminos


def test_consulta_corta_produce_escalera_corta():
    escalera = live_probe.escalera_de_consultas("miocarditis")

    assert escalera[0] == "miocarditis"
    assert all(len(e.split()) == 1 for e in escalera)


# ── Comportamiento de la sonda (con las fuentes simuladas) ───────────────────

def _oa_solo_si_es_corta(search_terms, limit=15, timeout=12.0):
    """Simula OpenAlex: una consulta larga no encuentra nada, una corta sí."""
    if len(search_terms.split()) <= 2:
        return ([{"title": "Instrumentos de percepción de salud en miocarditis",
                  "doi": "10.1000/escalera", "year": 2024, "source_engine": "openalex",
                  "authors": [], "keywords": ["miocarditis"]}], 1)
    return ([], 0)


def test_la_sonda_relaja_hasta_encontrar_y_lo_declara():
    with patch("radar.harvester.live_probe._probe_openalex", side_effect=_oa_solo_si_es_corta), \
         patch("radar.harvester.live_probe._probe_openaire", return_value=[]), \
         patch("radar.harvester.live_probe._probe_dialnet", return_value=[]):
        res = live_probe.probe_topic(PREGUNTA, compound_keywords=PALABRAS)

    assert res is not None
    assert len(res["articles"]) == 1
    assert res["relajada"] is True
    assert len(res["consulta_usada"].split()) <= 2
    assert len(res["intentos"]) >= 2
    assert res["intentos"][0]["resultados"] == 0
    assert res["intentos"][-1]["resultados"] == 1


def test_si_la_consulta_estricta_funciona_no_hay_relajacion():
    """Sin relajación no hay coste añadido: un solo intento, como antes."""
    with patch("radar.harvester.live_probe._probe_openalex") as oa, \
         patch("radar.harvester.live_probe._probe_openaire", return_value=[]), \
         patch("radar.harvester.live_probe._probe_dialnet", return_value=[]):
        oa.return_value = ([{"title": "Comunicación política comparada", "doi": "10.1/a",
                             "year": 2024, "source_engine": "openalex", "authors": [],
                             "keywords": ["comunicación política"]}], 1)
        res = live_probe.probe_topic("comunicación política")

    assert res["relajada"] is False
    assert len(res["intentos"]) == 1
    assert oa.call_count == 1


def test_sin_resultados_en_ningun_escalon_se_devuelve_el_diagnostico():
    with patch("radar.harvester.live_probe._probe_openalex", return_value=([], 0)), \
         patch("radar.harvester.live_probe._probe_openaire", return_value=[]), \
         patch("radar.harvester.live_probe._probe_dialnet", return_value=[]):
        res = live_probe.probe_topic(PREGUNTA, compound_keywords=PALABRAS)

    assert res is not None, "ya no devuelve None: devuelve el diagnóstico de lo intentado"
    assert res["articles"] == []
    assert res["consulta_usada"] is None
    assert len(res["intentos"]) >= 2
    assert all(i["resultados"] == 0 for i in res["intentos"])


def test_consulta_vacia_devuelve_none():
    assert live_probe.probe_topic("   ") is None


# ── Fase 2: entre términos sueltos gana el más específico ───────────────────

def _oa_por_termino(search_terms, limit=15, timeout=12.0):
    """Compuestas no encuentran nada; 'instrumentos' es genérico y 'miocarditis' raro."""
    termino = search_terms.strip().lower()
    if " " in termino:
        return ([], 0)
    if termino.startswith("instrumento"):
        return ([{"title": "Instrumentos de medida en salud", "doi": "10.1/gen",
                  "year": 2024, "source_engine": "openalex", "authors": [], "keywords": []}], 50_000)
    if termino.startswith("miocarditis"):
        return ([{"title": "Miocarditis: revisión", "doi": "10.1/raro",
                  "year": 2024, "source_engine": "openalex", "authors": [], "keywords": []}], 4_000)
    return ([], 0)


def test_entre_terminos_sueltos_se_elige_el_mas_raro():
    with patch("radar.harvester.live_probe._probe_openalex", side_effect=_oa_por_termino), \
         patch("radar.harvester.live_probe._probe_openaire", return_value=[]), \
         patch("radar.harvester.live_probe._probe_dialnet", return_value=[]):
        res = live_probe.probe_topic(PREGUNTA, compound_keywords=PALABRAS)

    assert res["consulta_usada"] == "miocarditis", "debe ganar el término con menos obras"
    assert res["relajada"] is True
    assert res["articles"][0]["doi"] == "10.1/raro"


# ── El aviso llega a la respuesta de la API ─────────────────────────────────

def test_el_endpoint_avisa_cuando_amplio_la_consulta(monkeypatch):
    """El investigador debe saber que los resultados no vienen de su formulación literal."""
    from fastapi.testclient import TestClient

    from radar import librarian
    from radar.api import main as api_main

    relajado = {
        "data_source": "live_probe", "probe_engine": "Sonda Federada", "articles": [
            {"title": "Instrumentos de percepción en salud", "doi": "10.1/x", "year": 2024,
             "source": "openalex", "source_engine": "openalex", "authors": [], "keywords": []}],
        "ecosystem": {"total_matched": 48, "sources": {"openalex_live": 1, "openaire_live": 0,
                                                      "dialnet_live": 0},
                      "top_journals": [], "years": {"min": 2024, "max": 2024, "recent_count": 1}},
        "saturation": {"level": "niche", "label": "Frontera", "description": "d", "review_count": 0},
        "top_authors": [], "suggested_keywords": [],
        "consulta_usada": "instrumentos escala paciente", "relajada": True,
        "intentos": [{"consulta": PREGUNTA, "resultados": 0},
                     {"consulta": "instrumentos escala paciente", "resultados": 48}],
    }
    monkeypatch.setattr(live_probe, "probe_topic", lambda **kw: relajado)
    monkeypatch.setattr(librarian, "listen", lambda *a, **k: {
        "mode": "deterministic", "corrected": PREGUNTA, "field_id": "comunicacion",
        "heard_as": "Ah, lo que usted busca es ...", "compound_keywords": PALABRAS})
    monkeypatch.setattr(librarian, "explain_results", lambda *a, **k: "Explicación del radar.")

    with patch("radar.api.main.db.connect") as conexion:
        conexion.return_value.execute.return_value.fetchall.return_value = []
        respuesta = TestClient(api_main.app).post("/api/librarian/assist",
                                                  json={"inquiry": PREGUNTA, "limit": 5})

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["consulta_relajada"] is True
    assert datos["consulta_usada"] == "instrumentos escala paciente"
    assert len(datos["consultas_intentadas"]) == 2
    assert "se amplió a «instrumentos escala paciente»" in datos["explanation"]
