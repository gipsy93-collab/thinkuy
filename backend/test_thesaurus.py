"""Pruebas del tesauro: esquema, integridad referencial y expansión de consultas.

El caso central es el que justifica el validador: un tesauro con referencias rotas o relaciones
asimétricas **no falla**, simplemente deja de expandir en silencio. Aquí se comprueba que eso
se declara.
"""
from radar import thesaurus

TESAURO = [
    {
        "id": "enfermedad-cardiovascular",
        "prefLabel": {"es": "enfermedad cardiovascular", "pt": "doença cardiovascular",
                      "en": "cardiovascular disease"},
        "altLabels": {"es": ["patología cardiovascular"], "pt": [], "en": []},
        "narrower": ["miocarditis"],
        "related": [],
        "note": "Términos de afectación del corazón y los vasos.",
        "source": "DeCS / Wikidata Q189790",
    },
    {
        "id": "miocarditis",
        "prefLabel": {"es": "miocarditis", "pt": "miocardite", "en": "myocarditis"},
        "altLabels": {"es": ["inflamación del miocardio"], "pt": [], "en": ["myocardial inflammation"]},
        "broader": ["enfermedad-cardiovascular"],
        "related": ["insuficiencia-cardiaca"],
        "note": "Inflamación del músculo cardíaco.",
        "source": "Wikidata Q186235",
    },
    {
        "id": "insuficiencia-cardiaca",
        "prefLabel": {"es": "insuficiencia cardíaca", "pt": "insuficiência cardíaca",
                      "en": "heart failure"},
        "altLabels": {"es": ["falla cardíaca"], "pt": [], "en": []},
        "related": ["miocarditis"],
        "source": "DeCS",
    },
]


# ── Validación: el esquema y la integridad ──────────────────────────────────

def test_tesauro_correcto_no_reporta_problemas():
    informe = thesaurus.validar(TESAURO)

    assert informe["resumen"]["valido"] is True
    assert informe["problemas"] == []
    assert informe["resumen"]["ids_unicos"] == 3


def test_detecta_referencia_rota():
    roto = [dict(TESAURO[1], broader=["concepto-que-no-existe"], **{"id": "miocarditis"})]

    problemas = thesaurus.validar(roto)["problemas"]

    assert any("que no existe" in p for p in problemas)


def test_detecta_asimetria_entre_mas_general_y_mas_especifico():
    """Si A dice que B es más general, B debe listar a A como más específico."""
    asimetrico = [
        {"id": "a", "prefLabel": {"es": "a"}, "broader": ["b"], "source": "s"},
        {"id": "b", "prefLabel": {"es": "b"}, "source": "s"},
    ]

    problemas = thesaurus.validar(asimetrico)["problemas"]

    assert any("asimetría" in p for p in problemas)


def test_detecta_sin_etiqueta_sin_fuente_y_duplicados():
    problemas = thesaurus.validar([
        {"id": "x", "prefLabel": {}, "source": ""},
        {"id": "y", "prefLabel": {"es": "y"}, "source": "s"},
        {"id": "y", "prefLabel": {"es": "y otra vez"}, "source": "s"},
    ])["problemas"]

    assert any("prefLabel" in p for p in problemas)
    assert any("source" in p for p in problemas)
    assert any("duplicado" in p for p in problemas)


def test_relacion_que_no_es_lista_se_reporta():
    problemas = thesaurus.validar([
        {"id": "z", "prefLabel": {"es": "z"}, "broader": "no-es-lista", "source": "s"}])["problemas"]

    assert any("debe ser una lista" in p for p in problemas)


# ── Búsqueda y expansión ────────────────────────────────────────────────────

def test_busqueda_insensible_a_acentos_y_mayusculas():
    assert thesaurus.buscar("MIOCARDITIS", TESAURO)["id"] == "miocarditis"
    # La búsqueda normaliza acentos: «miocardíte» (acento inexistente) cae en «miocardite» (PT).
    assert thesaurus.buscar("miocardíte", TESAURO)["id"] == "miocarditis"
    assert thesaurus.buscar("término que no está en el tesauro", TESAURO) is None


def test_encuentra_por_etiqueta_alternativa():
    assert thesaurus.buscar("inflamación del miocardio", TESAURO)["id"] == "miocarditis"


def test_expandir_trae_equivalencias_y_relaciones():
    expansion = thesaurus.expandir("miocarditis", TESAURO)

    assert expansion["encontrado"] is True
    assert "myocarditis" in expansion["equivalentes"]
    assert "inflamación del miocardio" in expansion["equivalentes"]
    assert "enfermedad cardiovascular" in expansion["mas_generales"]
    assert "insuficiencia cardíaca" in expansion["relacionados"]
    assert expansion["source"] == "Wikidata Q186235"


def test_expandir_un_termino_ausente_no_inventa():
    expansion = thesaurus.expandir("término que no está", TESAURO)

    assert expansion["encontrado"] is False
    assert expansion["equivalentes"] == []
    assert expansion["termino"] == "término que no está"


def test_expandir_consulta_declara_lo_que_no_cubre():
    resultado = thesaurus.expandir_consulta(["miocarditis", "periodismo"], TESAURO)

    assert "myocarditis" in resultado["ampliados"]
    assert "periodismo" in resultado["sin_cobertura"]
    assert resultado["equivalentes"]["miocarditis"]


def test_tesauro_vacio_no_rompe_nada():
    assert thesaurus.cargar(perfil=type("P", (), {"thesaurus": []})()) == []
    assert thesaurus.buscar("cualquiera", []) is None
    assert thesaurus.validar([])["resumen"]["valido"] is True
