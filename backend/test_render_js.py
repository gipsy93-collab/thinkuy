"""Pruebas del escalón 5 (navegador sin cabeza) — sin abrir ningún navegador.

Se prueba lo que decide el comportamiento: el permiso de `robots.txt`, la caché en disco
(la misma URL no se renderiza dos veces) y el rechazo declarado cuando no hay permiso.
"""
import httpx
import pytest

from radar.harvester import render_js


class RespuestaFalsa:
    def __init__(self, texto: str = "", status_code: int = 200):
        self.status_code = status_code
        self.text = texto
        self.content = texto.encode("utf-8")


class ClienteFalso:
    def __init__(self, robots: str | None = None, error: bool = False):
        self.robots = robots
        self.error = error
        self.llamadas: list[str] = []

    def get(self, url, **kwargs):
        self.llamadas.append(url)
        if self.error:
            raise httpx.ConnectError("sin red")
        if self.robots is None:
            return RespuestaFalsa("", status_code=404)
        return RespuestaFalsa(self.robots)

    def close(self):
        pass


ROBOTS = "User-agent: *\nDisallow: /privado\n"


# ── robots.txt ──────────────────────────────────────────────────────────────

def test_robots_permite_lo_no_listado():
    assert render_js.robots_permite("https://revista.edu/publico/1", ClienteFalso(ROBOTS)) is True


def test_robots_deniega_la_ruta_listada():
    assert render_js.robots_permite("https://revista.edu/privado/1", ClienteFalso(ROBOTS)) is False


def test_sin_robots_txt_no_hay_restriccion_declarada():
    assert render_js.robots_permite("https://revista.edu/x", ClienteFalso(None)) is True


def test_robots_inalcanzable_se_declara_como_no_verificable():
    """No se finge que se comprobó: se devuelve None."""
    assert render_js.robots_permite("https://revista.edu/x", ClienteFalso(error=True)) is None


def test_robots_con_url_invalida_no_lanza():
    assert render_js.robots_permite("") is None


# ── Caché en disco ──────────────────────────────────────────────────────────

def test_ruta_cache_es_estable_y_distinta_por_url():
    a1 = render_js.ruta_cache("https://revista.edu/a")
    a2 = render_js.ruta_cache("https://revista.edu/a")
    b = render_js.ruta_cache("https://revista.edu/b")

    assert a1 == a2
    assert a1 != b
    assert a1.suffix == ".html"


def test_cache_evita_renderizar_dos_veces(tmp_path, monkeypatch):
    destino = tmp_path / "pagina.html"
    destino.write_text("<html>ya renderizado</html>", encoding="utf-8")
    monkeypatch.setattr(render_js, "ruta_cache", lambda url: destino)

    def _no_renderizar(*a, **k):
        raise AssertionError("no debe renderizar si ya hay caché")

    monkeypatch.setattr(render_js, "render", _no_renderizar)

    html, de_cache = render_js.render_cacheado("https://revista.edu/a", http=ClienteFalso(ROBOTS))

    assert de_cache is True
    assert "ya renderizado" in html


def test_render_cacheado_guarda_el_resultado(tmp_path, monkeypatch):
    destino = tmp_path / "nueva.html"
    monkeypatch.setattr(render_js, "ruta_cache", lambda url: destino)
    monkeypatch.setattr(render_js, "render", lambda url, **k: "<html>fresco</html>")

    html, de_cache = render_js.render_cacheado("https://revista.edu/b", http=ClienteFalso(ROBOTS))

    assert de_cache is False
    assert "fresco" in html
    assert destino.read_text(encoding="utf-8") == "<html>fresco</html>"


def test_render_cacheado_respeta_robots_antes_de_renderizar(tmp_path, monkeypatch):
    monkeypatch.setattr(render_js, "ruta_cache", lambda url: tmp_path / "x.html")
    monkeypatch.setattr(render_js, "render",
                        lambda url, **k: pytest.fail("no debe renderizar sin permiso"))

    with pytest.raises(render_js.RobotsDenegado):
        render_js.render_cacheado("https://revista.edu/privado/1", http=ClienteFalso(ROBOTS))


# ── Disponibilidad ──────────────────────────────────────────────────────────

def test_disponible_devuelve_booleano():
    assert isinstance(render_js.disponible(), bool)
