"""Pruebas del Modo Revista (escalón 1) y del escalón 5 conectado a la cadena.

Sin red: se inyecta la cosecha OAI y el render del navegador con `monkeypatch`.
"""
import pytest
from fastapi.testclient import TestClient
from radar.api import main as api_main
from radar.harvester import ojs_oai, render_js

PERFIL = {"total": 24, "anio_min": 2019, "anio_max": 2019, "idiomas": {"es": 24},
          "cobertura": {"con_resumen": 24, "con_resumen_pct": 100.0,
                        "con_doi": 24, "con_doi_pct": 100.0, "con_palabras_clave": 24},
          "palabras_clave_frecuentes": {"cine": 12}}

ARTICULOS = [{"title": "Un artículo cosechado por OAI", "source": "ojs",
              "abstract": "Resumen que llegó en dc:description.",
              "doi": "10.1/x", "year": 2019, "keywords": ["cine"]}]


def cosecha_falsa(*args, **kwargs):
    return {"url": "https://revista.edu/index.php/r", "endpoint": "https://revista.edu/index.php/r/oai",
            "intentos": [], "repositorio": "Revista de Prueba", "total": 24,
            "perfil": PERFIL, "articulos": ARTICULOS}


@pytest.fixture()
def cliente_api():
    return TestClient(api_main.app)


# ── Modo Revista: POST /api/editorial/journal/profile ───────────────────────

def test_modo_revista_devuelve_la_huella_editorial(cliente_api, monkeypatch):
    monkeypatch.setattr(ojs_oai, "harvest_from_url", cosecha_falsa)

    r = cliente_api.post("/api/editorial/journal/profile",
                         json={"url": "https://revista.edu/index.php/r"})

    assert r.status_code == 200
    datos = r.json()
    assert datos["status"] == "ok"
    assert datos["endpoint"].endswith("/oai")
    assert datos["repositorio"] == "Revista de Prueba"
    assert datos["perfil"]["total"] == 24
    assert datos["perfil"]["cobertura"]["con_resumen_pct"] == 100.0
    # Por defecto NO se devuelven los artículos: el Modo Revista pide la huella, no el corpus.
    assert "articulos" not in datos


def test_modo_revista_puede_incluir_los_articulos(cliente_api, monkeypatch):
    monkeypatch.setattr(ojs_oai, "harvest_from_url", cosecha_falsa)

    datos = cliente_api.post("/api/editorial/journal/profile",
                             json={"url": "https://revista.edu/index.php/r",
                                   "incluir_articulos": True}).json()

    assert datos["articulos"][0]["abstract"] == "Resumen que llegó en dc:description."


def test_modo_revista_sin_url_devuelve_422(cliente_api):
    assert cliente_api.post("/api/editorial/journal/profile", json={}).status_code == 422


def test_modo_revista_declara_cuando_no_hay_endpoint(cliente_api, monkeypatch):
    monkeypatch.setattr(ojs_oai, "harvest_from_url",
                        lambda *a, **k: {"url": "x", "endpoint": None, "intentos": [],
                                         "articulos": [], "perfil": {},
                                         "detalle": "no se encontró endpoint OAI-PMH"})

    datos = cliente_api.post("/api/editorial/journal/profile", json={"url": "https://x.org"}).json()

    assert datos["status"] == "sin_endpoint"
    assert "no se encontró" in datos["detalle"]


# ── Escalón 5 conectado a la cadena del resumen ─────────────────────────────

HTML_SIN_RESUMEN = "<html><head><title>x</title></head><body>ficha sin metadatos</body></html>"
HTML_RENDERIZADO = ('<html><head>'
                    '<meta name="citation_abstract" content="Resumen que solo aparece al '
                    'ejecutar el JavaScript de la página, con longitud suficiente.">'
                    '</head><body>ya renderizado</body></html>')


def test_sin_render_js_no_se_usa_el_navegador(cliente_api, monkeypatch):
    def _no_llamar(*a, **k):
        raise AssertionError("no debe renderizar si render_js no se pide")

    monkeypatch.setattr(render_js, "render_cacheado", _no_llamar)

    datos = cliente_api.post("/api/metadata/abstract",
                             json={"html": HTML_SIN_RESUMEN, "url": "https://x.org/a"}).json()

    assert datos["status"] == "sin_resumen"
    assert datos["escalon"] == 2
    assert "render_js" not in datos


def test_render_js_opt_in_resuelve_el_resumen(cliente_api, monkeypatch):
    monkeypatch.setattr(render_js, "disponible", lambda: True)
    monkeypatch.setattr(render_js, "render_cacheado",
                        lambda url, **k: (HTML_RENDERIZADO, False))

    datos = cliente_api.post("/api/metadata/abstract",
                             json={"html": HTML_SIN_RESUMEN, "url": "https://x.org/a",
                                   "render_js": True}).json()

    assert datos["status"] == "ok"
    assert datos["escalon"] == 5
    assert datos["fuente"] == "citation_abstract"
    assert datos["render_js"]["usado"] is True
    assert "renderizar" in datos["detalle"]


def test_render_js_sin_playwright_lo_declara(cliente_api, monkeypatch):
    monkeypatch.setattr(render_js, "disponible", lambda: False)

    datos = cliente_api.post("/api/metadata/abstract",
                             json={"html": HTML_SIN_RESUMEN, "url": "https://x.org/a",
                                   "render_js": True}).json()

    assert datos["status"] == "sin_resumen"
    assert datos["render_js"]["usado"] is False
    assert "Playwright no está instalado" in datos["render_js"]["detalle"]


def test_render_js_que_no_aporta_nada_no_cambia_el_resultado(cliente_api, monkeypatch):
    monkeypatch.setattr(render_js, "disponible", lambda: True)
    monkeypatch.setattr(render_js, "render_cacheado",
                        lambda url, **k: (HTML_SIN_RESUMEN, True))

    datos = cliente_api.post("/api/metadata/abstract",
                             json={"html": HTML_SIN_RESUMEN, "url": "https://x.org/a",
                                   "render_js": True}).json()

    assert datos["status"] == "sin_resumen"
    assert datos["escalon"] == 2
    assert datos["render_js"]["usado"] is True
    assert datos["render_js"]["de_cache"] is True


def test_render_js_denegado_por_robots_se_declara(cliente_api, monkeypatch):
    monkeypatch.setattr(render_js, "disponible", lambda: True)

    def _denegar(url, **k):
        raise render_js.RobotsDenegado("robots.txt prohíbe consultar la URL")

    monkeypatch.setattr(render_js, "render_cacheado", _denegar)

    datos = cliente_api.post("/api/metadata/abstract",
                             json={"html": HTML_SIN_RESUMEN, "url": "https://x.org/a",
                                   "render_js": True}).json()

    assert datos["status"] == "sin_resumen"
    assert datos["render_js"]["usado"] is False
    assert "robots.txt" in datos["render_js"]["detalle"]
