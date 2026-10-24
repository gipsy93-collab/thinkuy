"""Pruebas de la escalera de acceso abierto al texto completo (`fulltext_oa`).

Cubre dos fallos medidos el 22-09-2026:
- El `citation_pdf_url` de SciELO venía con `&amp;` sin desescapar, así que SciELO ignoraba
  `format=pdf` y devolvía HTML.
- Unpaywall puede devolver una URL que sirve HTML: sin validar la descarga no había fallback.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient
from radar import config, db
from radar.api import main as api_main
from radar.harvester import fulltext_oa


class _Resp:
    def __init__(self, status=200, text="", content=b"", url="https://doi.org/10.1590/x", headers=None):
        self.status_code = status
        self.text = text
        self.content = content
        self.url = url
        self.headers = headers or {}


class _Router:
    """Cliente falso que responde por subcadena de URL."""

    def __init__(self, by_url):
        self.by_url = by_url

    def get(self, url, **kwargs):
        for clave, resp in self.by_url.items():
            if clave in str(url):
                return resp
        return _Resp(status=404)

    def close(self):
        pass


def _no_robots():
    return patch("radar.harvester.fulltext_oa.render_js.robots_permite", return_value=True)


def test_resolve_unpaywall_descarga_y_valida():
    router = _Router({"repo/x.pdf": _Resp(content=b"%PDF-1.7 data")})
    with _no_robots(), \
         patch("radar.harvester.unpaywall.enrich_doi",
               return_value={"is_oa": True, "pdf_url": "https://repo/x.pdf",
                             "oa_status": "gold", "host_type": "repository"}):
        res = fulltext_oa.resolve_pdf(router, "10.1234/abc")

    assert res["ruta"] == "unpaywall"
    assert res["body"] == b"%PDF-1.7 data"


def test_resolve_doi_citation_desescapa_amp():
    html = ('<html><head><meta name="citation_pdf_url" '
            'content="https://www.scielo.br/j/x/a/y/?lang=pt&amp;format=pdf">'
            '</head></html>')
    router = _Router({
        "doi.org": _Resp(text=html, url="https://www.scielo.br/j/x/a/y/"),
        "scielo.br/j/x/a/y": _Resp(content=b"%PDF-1.7 cuerpo"),
    })
    with _no_robots(), \
         patch("radar.harvester.unpaywall.enrich_doi", return_value={"is_oa": False}):
        res = fulltext_oa.resolve_pdf(router, "10.1590/abc")

    assert res["ruta"] == "doi_citation_pdf"
    # El `&amp;` debe quedar desescapado; si no, SciELO devuelve HTML en vez del PDF.
    assert res["pdf_url"] == "https://www.scielo.br/j/x/a/y/?lang=pt&format=pdf"
    assert res["body"] == b"%PDF-1.7 cuerpo"


def test_resolve_cae_a_segunda_ruta_si_la_primera_no_es_pdf():
    """Unpaywall devuelve una URL que sirve HTML: debe caer a citation_pdf_url."""
    html = ('<meta name="citation_pdf_url" content="https://www.scielo.br/j/x/a/y/?format=pdf">')
    router = _Router({
        "repo/html": _Resp(content=b"<html>no es pdf</html>"),
        "doi.org": _Resp(text=html, url="https://www.scielo.br/j/x/a/y/"),
        "scielo.br/j/x/a/y": _Resp(content=b"%PDF-1.7 bueno"),
    })
    with _no_robots(), \
         patch("radar.harvester.unpaywall.enrich_doi",
               return_value={"is_oa": True, "pdf_url": "https://repo/html"}):
        res = fulltext_oa.resolve_pdf(router, "10.1590/abc")

    assert res["ruta"] == "doi_citation_pdf"
    assert res["body"] == b"%PDF-1.7 bueno"


def test_resolve_sin_acceso_abierto():
    with patch("radar.harvester.unpaywall.enrich_doi", return_value={"is_oa": False}):
        res = fulltext_oa.resolve_pdf(_Router({}), "10.5555/cerrado")

    assert res["pdf_url"] is None
    assert res["body"] is None
    assert res["motivo"] == "sin_acceso_abierto"


def test_resolve_declara_sin_texto():
    html = "<html><body>No es posible acceder al texto completo</body></html>"
    router = _Router({"doi.org": _Resp(text=html, url="https://www.scielo.br/j/x/a/y/")})
    with _no_robots(), \
         patch("radar.harvester.unpaywall.enrich_doi", return_value={"is_oa": True}):
        res = fulltext_oa.resolve_pdf(router, "10.1590/abc")

    assert res["pdf_url"] is None
    assert res["motivo"] == "declarado_sin_texto"


def test_download_pdf_valida_magic():
    with _no_robots():
        assert fulltext_oa.download_pdf(_Router({"a.pdf": _Resp(content=b"%PDF-1.7")}), "https://x/a.pdf") \
            == b"%PDF-1.7"
        assert fulltext_oa.download_pdf(_Router({"a.pdf": _Resp(content=b"<html>")}), "https://x/a.pdf") is None
        assert fulltext_oa.download_pdf(
            _Router({"a.pdf": _Resp(status=403, content=b"%PDF")}), "https://x/a.pdf") is None


# ── Endpoint ────────────────────────────────────────────────────────────────

def _base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "ft.db")
    conn = db.connect()
    db.init_db(conn)
    conn.close()


def test_endpoint_sin_oa(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch)
    with patch("radar.harvester.fulltext_oa.resolve_pdf",
               return_value={"pdf_url": None, "body": None, "motivo": "sin_acceso_abierto", "ruta": None}):
        res = TestClient(api_main.app).post("/api/fulltext/fetch-oa/10.5555/cerrado")
    assert res.status_code == 200
    assert res.json()["status"] == "sin_oa"


def test_endpoint_ok(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch)
    with patch("radar.harvester.fulltext_oa.resolve_pdf",
               return_value={"pdf_url": "https://repo/x.pdf", "body": b"%PDF-1.7",
                             "ruta": "unpaywall", "oa_status": "gold",
                             "host_type": "repository"}), \
         patch("radar.text_extractor.extract_paper_to_markdown",
               return_value={"full_text": "cuerpo", "sections": {"metodos": "x"},
                             "word_count": 10, "page_count": 1, "references": []}), \
         patch("radar.text_extractor.ingest_fulltext_and_contexts",
               return_value={"citation_contexts_extracted": 0, "ingested_cited": []}):
        res = TestClient(api_main.app).post("/api/fulltext/fetch-oa/10.1590/abc")

    assert res.status_code == 200
    datos = res.json()
    assert datos["status"] == "ok"
    assert datos["ruta"] == "unpaywall"
    assert datos["pdf_url"] == "https://repo/x.pdf"
