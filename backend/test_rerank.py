"""Pruebas del re-ranker semántico opcional (BGE-M3) con un embedder falso.

No descarga el modelo: inyecta un codificador determinista para probar la lógica de ordenación
y la degradación. La medición con el modelo real se hace aparte (`tools/measure_rerank.py`).
"""
from unittest.mock import patch

from radar import config, rerank


def _normaliza(v):
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v] if n else v


def _vec(texto):
    t = (texto or "").lower()
    v = [
        1.0 if "ciencia" in t else 0.0,
        1.0 if "futbol" in t or "fútbol" in t else 0.0,
        1.0 if "gobernanza" in t or "marcos" in t or "normativ" in t else 0.0,
    ]
    return _normaliza(v)


class _FakeEmbedder:
    def encode(self, textos, **kwargs):
        return [_vec(t) for t in textos]


ARTICULOS = [
    {"doi": "10.1/futbol", "title": "El fútbol y su economía", "abstract": ""},
    {"doi": "10.1/ciencia", "title": "Marcos normativos de ciencia ciudadana", "abstract": "gobernanza"},
    {"doi": "10.1/otro", "title": "Recetas de cocina", "abstract": ""},
]


def test_rerank_ordena_por_similitud():
    orden, info = rerank.rerank(ARTICULOS, "marcos normativos ciencia ciudadana",
                                embedder=_FakeEmbedder())

    assert info["aplicado"] is True
    assert orden[0]["doi"] == "10.1/ciencia"
    assert orden[-1]["doi"] in ("10.1/futbol", "10.1/otro")


def test_rerank_sin_modelo_declara_sin_fallar():
    with patch.object(rerank, "disponible", return_value=False):
        orden, info = rerank.rerank(ARTICULOS, "cualquier cosa")

    assert info["aplicado"] is False
    assert info["motivo"] == "modelo_no_disponible"
    assert [a["doi"] for a in orden] == [a["doi"] for a in ARTICULOS]  # orden intacto


def test_rerank_consulta_vacia():
    _, info = rerank.rerank(ARTICULOS, "   ", embedder=_FakeEmbedder())
    assert info["aplicado"] is False
    assert info["motivo"] == "consulta_vacia"


def test_rerank_degrada_si_el_embedder_falla():
    class _Roto:
        def encode(self, *a, **k):
            raise RuntimeError("sin modelo")

    orden, info = rerank.rerank(ARTICULOS, "ciencia", embedder=_Roto())
    assert info["aplicado"] is False
    assert info["motivo"].startswith("error:")
    assert len(orden) == len(ARTICULOS)


def test_sugerir_vecindarios_agrupa_similares():
    arts = [
        {"doi": "10.1/a", "title": "Ciencia ciudadana en Brasil", "abstract": "gobernanza"},
        {"doi": "10.1/b", "title": "Ciencia ciudadana y políticas", "abstract": "marcos"},
        {"doi": "10.1/c", "title": "El fútbol profesional", "abstract": ""},
    ]
    grupos = rerank.sugerir_vecindarios(arts, embedder=_FakeEmbedder(), umbral=0.9)

    assert len(grupos) == 1
    assert grupos[0]["tamano"] == 2
    assert set(grupos[0]["dois"]) == {"10.1/a", "10.1/b"}


def test_activo_respeta_bandera_y_disponibilidad(monkeypatch):
    monkeypatch.setattr(config, "RERANK", "off")
    assert rerank.activo() is False
    monkeypatch.setattr(config, "RERANK", "bge-m3")
    with patch.object(rerank, "disponible", return_value=False):
        assert rerank.activo() is False
    with patch.object(rerank, "disponible", return_value=True):
        assert rerank.activo() is True


class _Contador:
    def __init__(self):
        self.llamadas = 0

    def encode(self, textos, **kwargs):
        self.llamadas += 1
        return [_vec(t) for t in textos]


def test_rerank_y_vecindarios_una_sola_codificacion():
    emb = _Contador()
    orden, info, grupos = rerank.rerank_y_vecindarios(
        ARTICULOS, "marcos normativos ciencia ciudadana", embedder=emb)

    assert info["aplicado"] is True
    assert emb.llamadas == 1, "debe codificar una sola vez (rerank + vecindarios juntos)"
    assert orden[0]["doi"] == "10.1/ciencia"


def test_probe_topic_expone_el_bloque_rerank():
    from radar.harvester import live_probe

    mock = [{"title": "Ciencia ciudadana", "doi": "10.1/x", "year": 2024,
             "source_engine": "openalex", "authors": [], "keywords": []}]
    with patch("radar.harvester.live_probe._probe_openalex", return_value=(mock, 1)), \
         patch("radar.harvester.live_probe._probe_openaire", return_value=[]), \
         patch("radar.harvester.live_probe._probe_dialnet", return_value=[]):
        res = live_probe.probe_topic("ciencia ciudadana")

    assert "rerank" in res
    assert res["rerank"]["aplicado"] is False  # apagado por defecto
    assert res["vecindarios_sugeridos"] == []
