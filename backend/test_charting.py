"""Pruebas de la propuesta asistida de PICC/PCC.

El caso central es el guardián: el motor **no puede** rellenar un campo con texto que no esté
literalmente en el resumen. Se midió (Hito 38) que un SLM fabrica contenido plausible cuando la
fuente no lo tiene; en una matriz de extracción eso contamina el informe.
"""
from fastapi.testclient import TestClient
from radar import charting
from radar.api import main as api_main

# Resumen estructurado real (el formato que publican SciELO y buena parte de OJS).
RESUMEN = (
    "Objetivo: analizar la relación entre liderazgo auténtico y síndrome de burnout en "
    "profesionales de enfermería de atención primaria. "
    "Métodos: estudio transversal con 220 participantes de seis centros de salud de Chile, "
    "mediante cuestionario autoadministrado. "
    "Resultados: se observó una asociación negativa entre liderazgo auténtico y agotamiento "
    "emocional, con diferencias significativas según la antigüedad. "
    "Conclusiones: el liderazgo auténtico se asocia a menor desgaste profesional. "
    "Limitaciones: el diseño transversal impide establecer causalidad."
)
TITULO = "Liderazgo auténtico y burnout en enfermería de atención primaria"


# ── Extracción determinista de resúmenes estructurados ──────────────────────

def test_extrae_los_campos_de_un_resumen_estructurado():
    campos = charting.extraer_estructurado(RESUMEN)

    assert "liderazgo auténtico" in campos["concept"].lower()
    assert "220 participantes" in campos["methodology"] or "220 participantes" in campos["population"]
    assert "asociación negativa" in campos["key_findings"].lower()
    assert "causalidad" in campos["limitations"].lower()


def test_un_resumen_no_estructurado_no_inventa_campos():
    assert charting.extraer_estructurado(
        "Este trabajo reflexiona sobre la práctica docente en contextos rurales sin etiquetas."
    ) == {}


def test_resumen_demasiado_corto_no_produce_nada():
    assert charting.extraer_estructurado("Objetivo: nada.") == {}


# ── La propuesta completa ──────────────────────────────────────────────────

def test_proponer_pcc_con_resumen_estructurado():
    resultado = charting.proponer_pcc(titulo=TITULO, resumen=RESUMEN, usar_modelo=False)

    assert resultado["campos"], "debe proponer al menos un campo"
    assert resultado["fuente"] == "determinista"
    # Todo lo propuesto debe estar literalmente en la fuente.
    for valor in resultado["campos"].values():
        assert charting._es_fiel(valor, f"{TITULO}. {RESUMEN}")


def test_sin_resumen_lo_declara_y_no_rellena():
    resultado = charting.proponer_pcc(titulo=TITULO, resumen="Corto.", usar_modelo=False)

    assert resultado["campos"] == {}
    assert "sin resumen utilizable" in resultado["declarado"]


# ── El guardián: lo que no está en la fuente se descarta ───────────────────

def test_el_guardian_descarta_lo_inventado_por_el_modelo(monkeypatch):
    """El modelo devuelve una población que NO está en el resumen: debe descartarse."""
    from radar import librarian
    monkeypatch.setattr(librarian, "available", lambda: True)
    monkeypatch.setattr(charting, "proponer_con_modelo", lambda *a, **k: {
        "population": "Hombres de 40 a 55 años de Bogotá",   # inventado
        "context": "atención primaria",                       # presente en el resumen
    })

    resultado = charting.proponer_pcc(titulo=TITULO, resumen=RESUMEN, usar_modelo=True)

    assert resultado["modelo_disponible"] is True
    assert "population" not in resultado["campos"], "lo inventado no puede entrar"
    assert resultado["campos"].get("context"), "lo que sí está literal sí entra"
    motivos = [d["motivo"] for d in resultado["descartados"]]
    assert any("no aparece literalmente" in m for m in motivos)


def test_el_guadian_no_deja_pasar_una_parafrasis(monkeypatch):
    """Una reformulación plausible tampoco es aceptable: no es citable."""
    from radar import librarian
    monkeypatch.setattr(librarian, "available", lambda: True)
    monkeypatch.setattr(charting, "proponer_con_modelo", lambda *a, **k: {
        "key_findings": "El liderazgo auténtico reduce el desgaste profesional del personal",
    })

    resultado = charting.proponer_pcc(titulo=TITULO, resumen=RESUMEN, usar_modelo=True)
    propuesto = resultado["campos"].get("key_findings") or ""

    if propuesto:
        assert charting._es_fiel(propuesto, RESUMEN), "si entra, es porque es literal"


def test_sin_modelo_encendido_lo_declara(monkeypatch):
    """Si el bibliotecario no está encendido, la respuesta debe decir POR QUÉ no propone."""
    from radar import librarian
    monkeypatch.setattr(librarian, "available", lambda: False)

    resultado = charting.proponer_pcc(
        titulo="Un estudio sobre algo", resumen=(
            "Este trabajo analiza la relevancia de la responsabilidad social universitaria en el "
            "ámbito internacional y revisa experiencias comparadas de varias universidades "
            "latinoamericanas durante la última década."), usar_modelo=True)

    assert resultado["modelo_disponible"] is False
    assert "no está encendido" in resultado["declarado"]


def test_limpia_escapes_literales_del_resumen():
    sucio = "Objetivo: analizar el tema.\\nMétodos: estudio transversal con 220 participantes."
    campos = charting.extraer_estructurado(charting.limpiar_escapes(sucio))

    assert campos, "con los escapes limpiados sí debe extraer"
    assert "\\n" not in campos["concept"]


def test_es_fiel_detecta_subcadena_con_acentos():
    assert charting._es_fiel("asociación negativa", "se observó una asociación negativa entre ambos")
    assert not charting._es_fiel("asociacion positiva", "se observó una asociación negativa entre ambos")


# ── El endpoint ────────────────────────────────────────────────────────────

def test_endpoint_propone_y_declara():
    cliente = TestClient(api_main.app)

    ok = cliente.post("/api/review/protocol/1/chart-propose",
                      json={"doi": "10.1/x", "title": TITULO, "abstract": RESUMEN,
                            "use_model": False})
    assert ok.status_code == 200
    datos = ok.json()
    assert datos["status"] == "ok"
    assert datos["campos"], "debe devolver propuesta"

    vacio = cliente.post("/api/review/protocol/1/chart-propose",
                         json={"doi": "10.1/y", "title": "T", "abstract": "Sin resumen.",
                               "use_model": False})
    assert vacio.status_code == 200
    assert vacio.json()["status"] == "sin_propuesta"
    assert vacio.json()["declarado"]
