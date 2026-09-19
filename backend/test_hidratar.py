"""Pruebas de la hidratación de resúmenes faltantes.

Cubre los tres desenlaces reales medidos en el protocolo del IP: recuperado por DOI, declarado
inexistente en fuentes abiertas, y bloqueado por la fuente. **Nunca se inventa un resumen.**
"""
import json
import sqlite3

import pytest

from radar import config, db
from radar.harvester import hidratar


class RespuestaFalsa:
    def __init__(self, datos, status_code=200):
        self.status_code = status_code
        self._datos = datos
        self.text = json.dumps(datos)
        self.content = self.text.encode("utf-8")

    def json(self):
        return self._datos


class ClienteFalso:
    """OpenAlex y Crossref simulados: responde solo a los DOI conocidos."""

    def __init__(self, con_resumen=None, con_doi=None, dialnet_503=False):
        self.con_resumen = con_resumen or {}
        self.con_doi = con_doi or {}
        self.dialnet_503 = dialnet_503
        self.llamadas = []

    def get(self, url, params=None, **kwargs):
        self.llamadas.append(url)
        if "dialnet" in url:
            return RespuestaFalsa("<html>503</html>", status_code=503 if self.dialnet_503 else 200)
        if "openalex.org" in url:
            doi = str((params or {}).get("filter", "")).replace("doi:", "").lower()
            if doi in self.con_resumen:
                # Índice invertido: {'palabra': [posiciones]}
                palabras = self.con_resumen[doi].split()
                indice = {p: [i] for i, p in enumerate(palabras)}
                return RespuestaFalsa({"results": [{"id": "W1", "doi": f"https://doi.org/{doi}",
                                                    "title": "Artículo",
                                                    "abstract_inverted_index": indice}]})
            if doi in self.con_doi:
                return RespuestaFalsa({"results": [{"id": "W1", "doi": f"https://doi.org/{doi}",
                                                    "title": "Artículo sin resumen"}]})
            return RespuestaFalsa({"results": []})
        if "crossref.org" in url:
            return RespuestaFalsa({"message": {}})
        return RespuestaFalsa({}, status_code=404)

    def close(self):
        pass


@pytest.fixture()
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "h.db")
    conn = db.connect()
    db.init_db(conn)
    pid = db.save_protocol(conn, {"title": "Protocolo de prueba", "research_question": "¿X?"})
    conn.close()
    return pid


def _incluir(pid, doi, decision="included"):
    conn = db.connect()
    try:
        db.save_screening(conn, pid, doi=doi, decision=decision)
    finally:
        conn.close()


def _resumen_de(pid, doi):
    conn = db.connect()
    try:
        fila = conn.execute(
            """SELECT a.abstract, s.article_id FROM article_screenings s
                 LEFT JOIN articles a ON a.id = s.article_id
                WHERE s.protocol_id = ? AND s.doi = ?""", (pid, doi.lower())).fetchone()
        return fila["abstract"] if fila else None, (fila["article_id"] if fila else None)
    finally:
        conn.close()


# ── Recuperado por DOI ─────────────────────────────────────────────────────

def test_recupera_el_resumen_por_doi_y_enlaza_el_cribado(base):
    """El caso de las tres filas que solo tenían un DOI: se llenan y se enlazan."""
    doi = "10.1016/j.ejca.2025.115711"
    _incluir(base, doi)
    cliente = ClienteFalso(con_resumen={doi: "Objetivo analizar el efecto del tratamiento en pacientes"})

    informe = hidratar.hidratar_resumenes(db.connect(), base, http=cliente)

    assert informe["recuperados"] == 1
    assert informe["enlazados"] == 1
    resumen, article_id = _resumen_de(base, doi)
    assert resumen and "efecto del tratamiento" in resumen
    assert article_id, "el cribado debe quedar enlazado al artículo indexado"


def test_si_la_fuente_no_publica_resumen_lo_declara(base):
    """Elsevier en The Lancet: ni OpenAlex ni Crossref traen el resumen. No se inventa."""
    doi = "10.1016/s0140-6736(18)32409-7"
    _incluir(base, doi)
    cliente = ClienteFalso(con_doi={doi: "sin resumen"})

    informe = hidratar.hidratar_resumenes(db.connect(), base, http=cliente)

    assert informe["recuperados"] == 0
    assert informe["no_disponibles"] == 1
    assert "no publica resumen" in informe["detalle_no_disponibles"][0]["motivo"]
    resumen, _ = _resumen_de(base, doi)
    assert not (resumen or "").strip(), "el campo debe quedar vacío, no inventado"


def test_si_la_fuente_bloquea_lo_distingue_de_no_existir(base):
    """Dialnet responde 503: se declara como bloqueo, no como ausencia del dato."""
    doi = "10.1000/dialnet.1"
    _incluir(base, doi)
    conn = db.connect()
    try:
        # El artículo existe pero sin resumen, con URL de Dialnet.
        _, aid = db.upsert_article(conn, {"title": "Exantema por pembrolizumab", "doi": doi,
                                          "source": "dialnet",
                                          "url": "https://dialnet.unirioja.es/servlet/articulo?codigo=1"})
        db.link_screening_article(conn, base, doi, aid)
    finally:
        conn.close()
    cliente = ClienteFalso(dialnet_503=True)

    informe = hidratar.hidratar_resumenes(db.connect(), base, http=cliente)

    assert informe["bloqueados_por_la_fuente"] == 1
    assert "no responde a nuestras peticiones" in informe["detalle_bloqueados"][0]["motivo"]


def test_sin_doi_ni_url_lo_declara(base):
    _incluir(base, "article:999999")
    cliente = ClienteFalso()

    informe = hidratar.hidratar_resumenes(db.connect(), base, http=cliente)

    assert informe["recuperados"] == 0
    assert informe["no_disponibles"] == 1
    assert "sin DOI resoluble" in informe["detalle_no_disponibles"][0]["motivo"]


def test_no_toca_los_que_ya_tienen_resumen(base):
    """Solo se hidratan los que faltan: no se reescribe lo que ya está."""
    doi = "10.1000/ya.tiene"
    # El artículo primero, para que el cribado quede enlazado (como en el flujo real).
    conn = db.connect()
    try:
        db.upsert_article(conn, {"title": "Con resumen", "doi": doi, "source": "test",
                                 "abstract": "Un resumen que ya estaba y no debe cambiar."})
    finally:
        conn.close()
    _incluir(base, doi)
    cliente = ClienteFalso(con_resumen={doi: "otro resumen distinto"})

    informe = hidratar.hidratar_resumenes(db.connect(), base, http=cliente)

    assert informe["recuperados"] == 0
    resumen, _ = _resumen_de(base, doi)
    assert resumen == "Un resumen que ya estaba y no debe cambiar.", "no se sobrescribe"


def test_el_endpoint_devuelve_el_informe(base, monkeypatch):
    from fastapi.testclient import TestClient

    from radar.api import main as api_main

    doi = "10.1016/j.ejca.2025.115711"
    _incluir(base, doi)
    monkeypatch.setattr(
        "radar.harvester.hidratar._articulo_por_doi",
        lambda http, d: type("A", (), {"db_row": lambda self: {"title": "T", "doi": d,
                                                               "abstract": "Resumen recuperado del DOI.",
                                                               "source": "openalex"},
                                       "abstract": "Resumen recuperado del DOI.",
                                       "doi": d})(),
    )

    datos = TestClient(api_main.app).post(
        f"/api/review/protocol/{base}/hydrate-abstracts", json={}).json()

    assert datos["status"] == "ok"
    assert datos["recuperados"] == 1
    assert datos["declaracion"]
