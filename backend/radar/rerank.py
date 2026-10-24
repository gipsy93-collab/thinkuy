"""Re-ordenación semántica **opcional** de los resultados de la sonda (BGE-M3).

Por qué existe (medido el 22-09-2026, `tools/probe_precision.py`): la sonda acierta en la
cabeza (precision@10 = 0,70) pero la cola decae (precision@50 = 0,16). El cuello no es *qué*
se recupera, sino *en qué orden*; este módulo reordena por similitud **híbrida** (denso + léxico).

Principios de diseño:

- **Opcional y degradable.** El servidor no depende de `torch` ni de `numpy`. Si el modelo no
  está disponible, `rerank()` devuelve el orden original y lo **declara**; nunca falla.
- **Sin `numpy`.** La similitud se calcula en Python puro (≤250 candidatos por consulta).
- **Señal, no decisión.** Reordena; el cribado lo arbitra el investigador.
- **Medible.** Se compara contra la línea base con `tools/probe_precision.py`.

Extra opcional: `pip install -r backend/requirements-rerank.txt` y `THINKUY_RERANK=bge-m3`.
"""
from __future__ import annotations

import logging

from . import config
from .normalize import norm

log = logging.getLogger("radar.rerank")

_EMBEDDER = None


def disponible() -> bool:
    """¿Está `sentence-transformers` instalado en este entorno?"""
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False


def activo() -> bool:
    """¿Debe reordenarse? Requiere la bandera encendida y el modelo disponible."""
    return config.RERANK not in ("off", "0", "", "none") and disponible()


def precargar() -> bool:
    """Carga el modelo por adelantado si el re-ranker está activo.

    Motivo medido (22-09-2026): la primera codificación paga la carga del modelo (~16 s en GPU);
    precargarlo al arrancar evita que la **primera búsqueda** lo cargue encima.
    """
    if not activo():
        return False
    try:
        _cargar()
        return True
    except Exception as e:
        log.warning("No se pudo precargar el re-ranker: %s", e)
        return False


def _cargar():
    """Carga perezosa del modelo (una sola vez por proceso).

    Se intenta primero `local_files_only=True`: con el modelo ya en caché carga en segundos y sin
    tocar el Hub (medido: la comprobación del Hub se colgaba en Windows). Si no está en caché, se
    permite la descarga (primera vez).
    """
    global _EMBEDDER
    if _EMBEDDER is None:
        from sentence_transformers import SentenceTransformer
        try:
            _EMBEDDER = SentenceTransformer(config.RERANK_MODEL, local_files_only=True)
        except Exception:
            log.info("Modelo %s no está en caché; se descarga (puede tardar).", config.RERANK_MODEL)
            _EMBEDDER = SentenceTransformer(config.RERANK_MODEL)
        # BGE-M3 trae 8192 tokens por defecto: para títulos + resúmenes es excesivo y dispara la
        # memoria. Se acota a 512 (medido: 106 candidatos colgaban sin el tope).
        try:
            _EMBEDDER.max_seq_length = 512
        except Exception:
            pass
    return _EMBEDDER


def _a_lista(vector) -> list[float]:
    """Convierte la salida del embedder (numpy o lista) a lista de flotantes."""
    try:
        return [float(x) for x in vector]
    except TypeError:
        return [float(vector)]


def _cos(a: list[float], b: list[float]) -> float:
    """Coseno. Con vectores normalizados es el producto punto."""
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))


def _texto(art: dict) -> str:
    return " ".join(str(x) for x in (art.get("title") or "", art.get("abstract") or "") if x).strip()


def _tokens(texto: str) -> set[str]:
    return {t for t in norm(texto or "").split() if len(t) >= 3}


def _score_lexico(q: set[str], d: set[str]) -> float:
    if not q:
        return 0.0
    return len(q & d) / len(q)


def _embeddings(embedder, textos: list[str]):
    """Codifica en lote; acepta cualquier objeto con `.encode`."""
    if not textos:
        return []
    vectores = embedder.encode(textos, normalize_embeddings=True, batch_size=16)
    return [_a_lista(v) for v in vectores]


def rerank(articles: list[dict], query: str, *, embedder=None,
           peso_denso: float | None = None) -> tuple[list[dict], dict]:
    """Reordena `articles` por similitud híbrida con `query`. Devuelve `(lista, info)`.

    `embedder` permite inyectar un codificador (pruebas o servicio externo). Si es `None` y el
    modelo no está disponible, devuelve el orden original con `info["aplicado"] = False`.
    """
    peso = config.RERANK_PESO_DENSO if peso_denso is None else peso_denso
    if not articles:
        return articles, {"aplicado": False, "motivo": "sin_candidatos"}
    consulta = (query or "").strip()
    if not consulta:
        return articles, {"aplicado": False, "motivo": "consulta_vacia"}

    if embedder is None:
        if not disponible():
            return articles, {"aplicado": False, "motivo": "modelo_no_disponible"}
        embedder = _cargar()

    try:
        textos = [_texto(a) for a in articles]
        vectores = _embeddings(embedder, [consulta] + textos)
    except Exception as e:  # degradación: nunca tumbar la búsqueda por el re-ranker
        log.warning("Re-ranker no disponible en ejecución: %s", e)
        return articles, {"aplicado": False, "motivo": f"error:{type(e).__name__}"}

    v_query = vectores[0]
    q_tokens = _tokens(consulta)
    puntuados = []
    for art, vec in zip(articles, vectores[1:]):
        denso = max(0.0, _cos(v_query, vec))
        lexico = _score_lexico(q_tokens, _tokens(_texto(art)))
        art["_rerank_score"] = round(peso * denso + (1 - peso) * lexico, 4)
        puntuados.append(art)

    puntuados.sort(key=lambda a: a.get("_rerank_score", 0.0), reverse=True)
    info = {"aplicado": True, "modelo": config.RERANK_MODEL, "peso_denso": peso,
            "candidatos": len(puntuados)}
    return puntuados, info


def _grupos_de_vectores(vectores: list[list[float]], items: list[dict],
                        umbral: float) -> list[dict]:
    """Componentes conexas por similitud ≥ umbral (Union-Find). Solo grupos de 2 o más."""
    n = len(items)
    padre = list(range(n))

    def _raiz(i: int) -> int:
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _cos(vectores[i], vectores[j]) >= umbral:
                ri, rj = _raiz(i), _raiz(j)
                if ri != rj:
                    padre[rj] = ri

    grupos: dict[int, list[int]] = {}
    for i in range(n):
        grupos.setdefault(_raiz(i), []).append(i)

    salida = []
    for miembros in grupos.values():
        if len(miembros) < 2:
            continue
        salida.append({
            "tamano": len(miembros),
            "dois": [items[i].get("doi") for i in miembros],
            "titulos": [items[i].get("title") for i in miembros],
        })
    salida.sort(key=lambda g: g["tamano"], reverse=True)
    return salida


def sugerir_vecindarios(articles: list[dict], *, embedder=None, umbral: float = 0.75,
                        max_n: int = 60) -> list[dict]:
    """Agrupa por similitud semántica los primeros `max_n` resultados (componentes conexas).

    Es una **sugerencia** de vecindario epistémico, no una asignación: solo se devuelven grupos
    de dos o más obras. Con `embedder=None` usa el modelo disponible; sin él, devuelve `[]`.
    """
    if not articles:
        return []
    if embedder is None:
        if not disponible():
            return []
        embedder = _cargar()
    muestra = articles[:max_n]
    try:
        vectores = _embeddings(embedder, [_texto(a) for a in muestra])
    except Exception as e:
        log.warning("Vecindarios: embeddings no disponibles: %s", e)
        return []
    return _grupos_de_vectores(vectores, muestra, umbral)


def rerank_y_vecindarios(articles: list[dict], query: str, *, embedder=None,
                         peso_denso: float | None = None, umbral: float = 0.75,
                         max_n: int = 60) -> tuple[list[dict], dict, list[dict]]:
    """Reordena y sugiere vecindarios con **una sola codificación**.

    Motivo medido (22-09-2026): encadenar `rerank` + `sugerir_vecindarios` codificaba dos veces
    (los mismos textos y 60 más), y en CPU eso sumaba ~100 s. Devuelve
    `(ordenados, info, vecindarios)`.
    """
    peso = config.RERANK_PESO_DENSO if peso_denso is None else peso_denso
    if not articles:
        return articles, {"aplicado": False, "motivo": "sin_candidatos"}, []
    consulta = (query or "").strip()
    if not consulta:
        return articles, {"aplicado": False, "motivo": "consulta_vacia"}, []
    if embedder is None:
        if not disponible():
            return articles, {"aplicado": False, "motivo": "modelo_no_disponible"}, []
        embedder = _cargar()

    try:
        vectores = _embeddings(embedder, [consulta] + [_texto(a) for a in articles])
    except Exception as e:  # degradación: nunca tumbar la búsqueda por el re-ranker
        log.warning("Re-ranker no disponible en ejecución: %s", e)
        return articles, {"aplicado": False, "motivo": f"error:{type(e).__name__}"}, []

    v_query, vecs = vectores[0], vectores[1:]
    q_tokens = _tokens(consulta)
    pares: list[tuple[dict, list[float]]] = []
    for art, vec in zip(articles, vecs):
        denso = max(0.0, _cos(v_query, vec))
        lexico = _score_lexico(q_tokens, _tokens(_texto(art)))
        art["_rerank_score"] = round(peso * denso + (1 - peso) * lexico, 4)
        pares.append((art, vec))

    pares.sort(key=lambda p: p[0].get("_rerank_score", 0.0), reverse=True)
    ordenados = [p[0] for p in pares]
    info = {"aplicado": True, "modelo": config.RERANK_MODEL, "peso_denso": peso,
            "candidatos": len(ordenados)}
    vecindarios = _grupos_de_vectores([p[1] for p in pares][:max_n], ordenados[:max_n], umbral)
    return ordenados, info, vecindarios
