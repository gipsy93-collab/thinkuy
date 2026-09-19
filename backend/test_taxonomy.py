"""Pruebas de la disciplina derivada (Wikidata `subclase de`) y su guardián anti-contaminación.

Sin red: el cliente HTTP se inyecta con respuestas canónicas de la API de Wikidata y la caché
se aísla en un archivo temporal (`_guardar_cache` se neutraliza).
"""
import json

import pytest

from radar import taxonomy


class RespuestaFalsa:
    def __init__(self, datos, status_code=200):
        self.status_code = status_code
        self._datos = datos
        self.text = json.dumps(datos)

    def json(self):
        return self._datos


class ClienteWikidata:
    """Grafo mínimo controlado: búsquedas concepto->qid y entidades qid->padre."""

    def __init__(self, busquedas: dict, entidades: dict):
        self.busquedas = busquedas
        self.entidades = entidades
        self.llamadas = []

    def get(self, url, params=None, **kwargs):
        params = params or {}
        accion = params.get("action")
        self.llamadas.append({"action": accion})
        if accion == "wbsearchentities":
            qid = self.busquedas.get(str(params.get("search", "")).lower())
            return RespuestaFalsa({"search": [{"id": qid}] if qid else []})
        if accion == "wbgetentities":
            salida = {}
            for qid in str(params.get("ids", "")).split("|"):
                dato = self.entidades.get(qid)
                if not dato:
                    continue
                padre = dato.get("padre")
                claims = {"P279": []} if not padre else {
                    "P279": [{"mainsnak": {"datavalue": {"value": {"id": padre}}}}]}
                salida[qid] = {"labels": {k: {"value": v} for k, v in dato["labels"].items()},
                               "claims": claims}
            return RespuestaFalsa({"entities": salida})
        return RespuestaFalsa({}, status_code=404)

    def close(self):
        pass


@pytest.fixture()
def cache_limpia(tmp_path, monkeypatch):
    """Aísla la caché en un archivo temporal, pero deja que se lea y escriba de verdad.

    Neutralizar el guardado haría pasar las pruebas de caché sin ejercer la persistencia real.
    """
    monkeypatch.setattr(taxonomy, "CACHE_PATH", tmp_path / "cache.json")
    return tmp_path


def _etiq(nombre_es: str) -> dict:
    return {"labels": {"es": nombre_es, "pt": nombre_es, "en": nombre_es}}


# ══════════════════════════════════════════════════════════════════════════
# Resolución y cadena
# ══════════════════════════════════════════════════════════════════════════

def test_resuelve_y_cachea(cache_limpia):
    cliente = ClienteWikidata({"miocarditis": "Q1"}, {"Q1": {**_etiq("miocarditis"), "padre": None}})

    assert taxonomy.resolver("miocarditis", cliente) == "Q1"
    antes = len(cliente.llamadas)
    assert taxonomy.resolver("miocarditis", cliente) == "Q1"
    assert len(cliente.llamadas) == antes, "la segunda consulta debe salir de la caché"


def test_concepto_no_resoluble_devuelve_none(cache_limpia):
    """No se inventa: si la taxonomía no lo conoce, se declara."""
    assert taxonomy.resolver("concepto inexistente", ClienteWikidata({}, {})) is None


def test_cadena_sigue_el_primer_padre_y_trae_etiquetas(cache_limpia):
    cliente = ClienteWikidata({"miocarditis": "Q1"}, {
        "Q1": {**_etiq("miocarditis"), "padre": "Q4"},
        "Q4": {**_etiq("cardiopatía"), "padre": "Q7"},
        "Q7": {**_etiq("enfermedad"), "padre": None},
    })

    trayecto = taxonomy.cadena("miocarditis", niveles=5, http=cliente)

    assert [p["qid"] for p in trayecto] == ["Q1", "Q4", "Q7"]
    assert trayecto[2]["es"] == "enfermedad"


def test_cadena_respeta_el_maximo_de_niveles(cache_limpia):
    cliente = ClienteWikidata({"x": "Q1"}, {
        "Q1": {**_etiq("n1"), "padre": "Q2"}, "Q2": {**_etiq("n2"), "padre": "Q3"},
        "Q3": {**_etiq("n3"), "padre": "Q4"}, "Q4": {**_etiq("n4"), "padre": None}})

    assert len(taxonomy.cadena("x", niveles=2, http=cliente)) == 2


def test_cadena_vacia_si_no_se_resuelve(cache_limpia):
    assert taxonomy.cadena("no existe", http=ClienteWikidata({}, {})) == []


# ══════════════════════════════════════════════════════════════════════════
# El guardián anti-contaminación
# ══════════════════════════════════════════════════════════════════════════

GRAFO_QUE_REPARTE = {
    # nivel 1: tres nodos distintos · nivel 2: tres nodos distintos
    # nivel 3: X y Y (2 de 3 en Y: 67 %) -> COLAPSA y debe quedar excluido
    # nivel 4: R en los tres (100 %) -> COLAPSA
    "Q1": {**_etiq("miocarditis"), "padre": "A"},
    "Q2": {**_etiq("cáncer de riñón"), "padre": "B"},
    "Q3": {**_etiq("periodismo"), "padre": "C"},
    "A": {**_etiq("cardiología"), "padre": "X"},
    "B": {**_etiq("oncología"), "padre": "Y"},
    "C": {**_etiq("comunicación"), "padre": "Y"},
    "X": {**_etiq("medicina"), "padre": "R"},
    "Y": {**_etiq("ciencias sociales"), "padre": "R"},
    "R": {**_etiq("entidad"), "padre": None},
}
BUSQUEDAS = {"miocarditis": "Q1", "cáncer de riñón": "Q2", "periodismo": "Q3"}


def test_el_guardian_excluye_los_niveles_que_colapsan(cache_limpia):
    cliente = ClienteWikidata(BUSQUEDAS, GRAFO_QUE_REPARTE)

    niveles = taxonomy.concentracion_por_nivel(list(BUSQUEDAS), cliente)

    util = {f["nivel"]: f["utilizable"] for f in niveles}
    assert util[1] is True and util[2] is True, "los niveles que reparten deben ser utilizables"
    assert util[3] is False and util[4] is False, "los niveles que colapsan deben quedar excluidos"
    assert niveles[2]["etiqueta_mayor"] == "ciencias sociales"
    assert niveles[3]["etiqueta_mayor"] == "entidad", "la raíz del grafo no es una disciplina"


def test_la_disciplina_usa_el_nivel_mas_profundo_que_reparte(cache_limpia):
    cliente = ClienteWikidata(BUSQUEDAS, GRAFO_QUE_REPARTE)

    resultado = taxonomy.disciplina_de(list(BUSQUEDAS), cliente)

    assert resultado["nivel_usado"] == 2, "debe elegir el nivel 2, no el 3 que colapsa"
    assert set(resultado["nodos"]) == {"cardiología", "oncología", "comunicación"}
    assert "nivel 2" in resultado["motivo"]


def test_si_ningun_nivel_reparte_lo_declara_en_vez_de_inventar(cache_limpia):
    """Solo un concepto resoluble: todos los niveles concentran el 100 % en un nodo."""
    cliente = ClienteWikidata({"miocarditis": "Q1"}, {
        "Q1": {**_etiq("miocarditis"), "padre": "R"}, "R": {**_etiq("entidad"), "padre": None}})

    resultado = taxonomy.disciplina_de(["miocarditis", "no existe A", "no existe B"], cliente)

    assert resultado["nivel_usado"] is None
    assert "no se deriva para no contaminar" in resultado["motivo"]
    assert len(resultado["sin_resolver"]) == 2, "los no resueltos se declaran"


# ── El segundo criterio del guardián: la ontología superior ─────────────────

GRAFO_CON_ONTOLOGIA = {
    # nivel 1: tres nodos distintos (Q1, Q2, Q3) -> utilizable
    # nivel 2: tres nodos, pero uno es «entidad» -> el nivel se RECHAZA aunque reparta
    "Q1": {**_etiq("miocarditis"), "padre": "E"},
    "Q2": {**_etiq("periodismo"), "padre": "X"},
    "Q3": {**_etiq("biodiversidad"), "padre": "Y"},
    "E": {**_etiq("entidad"), "padre": None},
    "X": {**_etiq("ciencias sociales"), "padre": None},
    "Y": {**_etiq("ciencias naturales"), "padre": None},
}


def test_un_nivel_que_reparte_pero_es_ontologico_se_rechaza(cache_limpia):
    """Medido en vivo: el nivel 8 «repartía» pero sus nodos eran «quality» y «fenómeno»."""
    cliente = ClienteWikidata({"miocarditis": "Q1", "periodismo": "Q2", "biodiversidad": "Q3"},
                              GRAFO_CON_ONTOLOGIA)

    niveles = taxonomy.concentracion_por_nivel(["miocarditis", "periodismo", "biodiversidad"], cliente)
    por_nivel = {f["nivel"]: f for f in niveles}

    assert por_nivel[2]["concentracion"] < taxonomy.UMBRAL_CONCENTRACION, "reparte"
    assert por_nivel[2]["ontologicas"] == ["entidad"], "pero hay un nodo de la ontología superior"
    assert por_nivel[2]["utilizable"] is False, "y por eso no se usa"


def test_la_disciplina_no_sube_a_la_ontologia(cache_limpia):
    cliente = ClienteWikidata({"miocarditis": "Q1", "periodismo": "Q2", "biodiversidad": "Q3"},
                              GRAFO_CON_ONTOLOGIA)

    resultado = taxonomy.disciplina_de(["miocarditis", "periodismo", "biodiversidad"], cliente)

    assert resultado["nivel_usado"] == 1, "debe quedarse en el nivel que sí son disciplinas"
    assert resultado["concentracion"] == 0.333 or resultado["concentracion"] < 0.5
    assert "entidad" not in str(resultado["nodos"])


def test_la_trayectoria_completa_se_conserva_aunque_la_disciplina_se_acote(cache_limpia):
    """El trayecto es lo informativo: se devuelve entero aunque la etiqueta se limite."""
    cliente = ClienteWikidata({"miocarditis": "Q1"}, {
        "Q1": {**_etiq("miocarditis"), "padre": "C"}, "C": {**_etiq("cardiología"), "padre": "M"},
        "M": {**_etiq("medicina"), "padre": "E"}, "E": {**_etiq("entidad"), "padre": None}})

    resultado = taxonomy.disciplina_de(["miocarditis"], cliente)

    nombres = [p["es"] for p in resultado["trayectoria"]["miocarditis"]]
    assert nombres == ["miocarditis", "cardiología", "medicina", "entidad"]
    assert resultado["nivel_usado"] is None, "un solo concepto no permite derivar disciplina"


def test_sin_conceptos_no_hay_disciplina(cache_limpia):
    resultado = taxonomy.disciplina_de([], ClienteWikidata({}, {}))

    assert resultado["nivel_usado"] is None
    assert "sin conceptos" in resultado["motivo"]


def test_la_trayectoria_es_lo_que_informa_no_el_destino(cache_limpia):
    """El destino es «entidad» y no informa; el trayecto sí."""
    cliente = ClienteWikidata(BUSQUEDAS, GRAFO_QUE_REPARTE)

    resultado = taxonomy.disciplina_de(["miocarditis"], cliente)

    trayecto = resultado["trayectoria"]["miocarditis"]
    nombres = [p["es"] for p in trayecto]
    assert nombres == ["miocarditis", "cardiología", "medicina", "entidad"]
    assert nombres[-1] == "entidad" and nombres[1] == "cardiología"
