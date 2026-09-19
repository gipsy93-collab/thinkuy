"""GARANTÍAS ANTI-MONOTEMÁTICAS: activar un campo de referencia no debe sesgar la búsqueda.

Pregunta del IP al elegir «Ciencia Abierta»: *«solo espero que eso no convierta a la
herramienta monotemática ¿se asegura de eso?»*. Es exactamente el riesgo del fantasma de
`comunicacion`, así que no se responde con una promesa: se responde con estas pruebas.

Se garantizan tres cosas, cada una comprobable:

  G1. **Ningún campo es el valor por defecto** — el activo es `general` (neutro).
  G2. **La búsqueda en vivo NO usa los términos del perfil.** El perfil aporta semillas para
      cosechar, temas para etiquetar y vocabulario para emparejar; no filtra la consulta.
  G3. **El campo puede decir «esta consulta no es mía».**
"""
import json

from radar import config, profile, thesaurus
from radar.harvester import live_probe

# ── G1: ningún campo por defecto ────────────────────────────────────────────

def test_ningun_campo_de_referencia_es_el_activo():
    assert config.THINKUY_FIELD == "general"
    assert profile.field_profile.id == "general"
    assert profile.field_profile.topics == []


def test_los_campos_de_referencia_existen_pero_no_se_imponen():
    disponibles = profile.available_fields()

    assert "ciencia_abierta" in disponibles, "el campo de referencia debe existir"
    assert "general" in disponibles and profile.field_profile.id == "general"


# ── G2: la búsqueda no depende del perfil ───────────────────────────────────

def test_la_sonda_en_vivo_no_depende_del_perfil():
    """Si `live_probe` importara el perfil, la búsqueda podría sesgarse por campo."""
    import inspect

    fuente = inspect.getsource(live_probe)

    assert "profile" not in fuente, "la sonda en vivo no debe consultar el perfil de campo"
    assert "field_profile" not in fuente


def test_los_terminos_de_busqueda_salen_de_la_consulta_no_del_perfil():
    """La sonda recibe la consulta; no añade descriptores del campo por su cuenta."""
    firma = __import__("inspect").signature(live_probe.probe_topic)

    assert "query" in firma.parameters
    assert "compound_keywords" in firma.parameters
    assert not any("field" in p or "profile" in p for p in firma.parameters)


# ── G3: el campo puede declinar ─────────────────────────────────────────────

def test_el_campo_activo_declara_fuera_de_campo(monkeypatch):
    """Una consulta clínica con el campo de Ciencia Abierta activo NO debe etiquetarse."""
    from radar import librarian

    campos = profile.load_profile("ciencia_abierta").topics
    monkeypatch.setattr(librarian, "available", lambda: True)
    monkeypatch.setattr(librarian, "_chat", lambda *a, **k: json.dumps({
        "corrected": "instrumentos para valorar miocarditis",
        "heard_as": "Ah, lo que usted busca es instrumentos para valorar miocarditis",
        "compound_keywords": ["instrumentos", "miocarditis"],
        "field_id": "ninguno", "confidence": "low"}))

    escucha = librarian.listen("instrumentos para valorar miocarditis", campos)

    assert escucha["field_id"] == "ninguno"
    assert escucha.get("fuera_del_campo") is True, "debe declararse fuera de campo"


def test_un_campo_inventado_por_el_modelo_no_cae_en_el_primer_tema(monkeypatch):
    """Antes, un `field_id` desconocido caía al PRIMER tema del perfil y lo disfrazaba."""
    from radar import librarian

    campos = profile.load_profile("ciencia_abierta").topics
    primer_tema = campos[0]["id"]
    monkeypatch.setattr(librarian, "available", lambda: True)
    monkeypatch.setattr(librarian, "_chat", lambda *a, **k: json.dumps({
        "corrected": "algo de astrofísica", "heard_as": "Ah, lo que usted busca es astrofísica",
        "compound_keywords": ["astrofísica"], "field_id": "astrofisica_observacional",
        "confidence": "low"}))

    escucha = librarian.listen("algo de astrofísica", campos)

    assert escucha["field_id"] != primer_tema, "no debe disfrazarse con el primer tema del campo"
    assert escucha["field_id"] == "ninguno"


def test_un_campo_valido_sigue_asignandose(monkeypatch):
    """La garantía no rompe el caso legítimo: una consulta del campo sí se clasifica."""
    from radar import librarian

    campos = profile.load_profile("ciencia_abierta").topics
    esperado = campos[0]["id"]
    monkeypatch.setattr(librarian, "available", lambda: True)
    monkeypatch.setattr(librarian, "_chat", lambda *a, **k: json.dumps({
        "corrected": "altmetría en revistas iberoamericanas",
        "heard_as": "Ah, lo que usted busca es altmetría en revistas iberoamericanas",
        "compound_keywords": ["altmetría"], "field_id": esperado, "confidence": "high"}))

    escucha = librarian.listen("altmetría en revistas iberoamericanas", campos)

    assert escucha["field_id"] == esperado


# ── El tesauro informa, no filtra ───────────────────────────────────────────

def test_el_tesauro_expande_pero_declara_lo_que_no_cubre():
    perfil = profile.load_profile("ciencia_abierta")
    entradas = perfil.thesaurus
    assert entradas, "el campo de referencia debe traer su tesauro piloto"

    resultado = thesaurus.expandir_consulta(["bibliometría", "miocarditis"], entradas)

    assert "myocarditis" not in " ".join(resultado["ampliados"]).lower(), \
        "el tesauro no debe inventar equivalencias de términos que no cubre"
    assert "miocarditis" in resultado["sin_cobertura"]
    assert resultado["equivalentes"]["bibliometría"], "pero sí expande lo que sí cubre"


def test_el_tesauro_del_campo_es_valido():
    perfil = profile.load_profile("ciencia_abierta")

    informe = thesaurus.validar(perfil.thesaurus)

    assert informe["resumen"]["valido"] is True
    assert informe["problemas"] == []
    assert informe["resumen"]["entradas"] >= 60


def test_los_temas_del_campo_de_referencia_son_del_dominio():
    """No debe colarse taxonomía de otra disciplina (el fantasma de comunicación)."""
    perfil = profile.load_profile("ciencia_abierta")
    nombres = " ".join(t.get("name", "") for t in perfil.topics).lower()

    for señal in ("métrica", "ciencia abierta", "comunicación científica", "bibliotec"):
        assert señal in nombres, f"falta «{señal}» en los temas del campo"
    assert "ecología de los medios" not in nombres
