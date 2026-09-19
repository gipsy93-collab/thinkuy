"""Disciplina derivada del grafo de conceptos (Wikidata `subclase de`), no escrita a mano.

**Por qué existe.** Un campo de conocimiento escrito a mano como valor por defecto terminó
contaminando toda búsqueda (el «fantasma» de `comunicacion`, Hito 45). La disciplina debe
**derivarse** de los conceptos que la consulta contiene, subiendo por una taxonomía explícita.

**Qué se midió antes de construirlo** (`tools/sondar_taxonomias.py`, 38 conceptos reales, Hito 48):

  * Wikidata resuelve **37/38 (97 %)** con etiquetas **ES 95 % / PT 82 % / EN 100 %**.
  * OpenAlex resuelve 23/38 (61 %) y **falla en español** (`comunicación`, `filosofía`,
    `epistemología`, `elecciones`) → queda como señal secundaria, nunca como disciplina.
  * La cadena de Wikidata **reparte hasta el nivel 9**; el 10 colapsa (55 % en «entidad»).
  * El dominio de OpenAlex concentra el **83 %** en «Social Sciences» → excluido.

**GUARDIÁN OBLIGATORIO (anti-contaminación).** Un nivel de la taxonomía **solo se usa si
reparte**: más de un nodo distinto y el mayor con **menos del 50 %** de los conceptos. Un nivel
que se lo traga todo no informa — y la raíz del grafo («entidad») no es una disciplina.

El destino no sirve; el trayecto sí: `miocarditis → miocardiopatía → cardiopatía →
enfermedad cardiovascular → …` es la información útil, no «entidad».
"""
from __future__ import annotations

import json
import logging
import time
from collections import Counter

import httpx

from . import config
from .normalize import norm

log = logging.getLogger("radar.taxonomy")

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
CABECERAS = {"User-Agent": config.USER_AGENT}

CACHE_PATH = config.DATA_DIR / "cache_taxonomia.json"

NIVELES = 8
UMBRAL_CONCENTRACION = 0.50
MIN_NODOS = 2

# ── Calibración medida (18-09-2026) ─────────────────────────────────────────
# El guardián por CONCENTRACIÓN no basta, y lo destapó una prueba en vivo del propio módulo:
# con cinco conceptos dispares, el nivel 8 «repartía» (25 % cada uno) pero sus nodos eran
# `problema de salud`, `enfermedad`, **`quality`** y **`fenómeno`** — categorías ontológicas,
# no disciplinas. A partir de cierto nivel la cadena de `subclase de` deja de describir
# campos de conocimiento y describe la ontología superior de Wikidata.
#
# Dos correcciones, ambas declaradas como **calibrables**:
#   1. `NIVEL_MAXIMO_DISCIPLINA`: la sonda (Hito 48) midió que los niveles 1–4 tienen entre
#      24 y 37 nodos distintos con ≤7 % de concentración — nodos reconocibles como disciplina
#      (`cardiología`, `comunicación`, `biología`). Más arriba, no.
#   2. `CATEGORIAS_ONTOLOGICAS`: nodos que aparecen como ancestro absorbente en las pruebas
#      en vivo y en la sonda. Si el nodo dominante de un nivel es uno de ellos, el nivel se
#      rechaza aunque reparta. **Una calibración sobre 300 conceptos puede sustituir esta
#      lista por umbrales medidos**, pero el criterio (rechazar la ontología superior) se queda.
NIVEL_MAXIMO_DISCIPLINA = 4
CATEGORIAS_ONTOLOGICAS = frozenset({
    "entidad", "entity", "ente", "entidad bfo", "bfo entity",
    "fenómeno", "fenomeno", "phenomenon",
    "quality", "cualidad", "propiedad", "property",
    "proceso", "process", "ocurrencia", "ocurrence", "occurrence", "evento", "event",
    "sistema conceptual", "conceptual system", "abstracción", "abstraction",
    "objeto", "object", "continuante", "continuant", "occurrente", "occurrent",
    "entidad colectiva", "collective entity", "entidad física", "physical entity",
})
_ONTOLOGICAS_NORM = frozenset(norm(c) for c in CATEGORIAS_ONTOLOGICAS)


# ---------------------------------------------------------------- caché

def _leer_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"conceptos": {}, "cadenas": {}}


def _guardar_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log.warning("no se pudo guardar la caché de taxonomía: %s", e)


# ---------------------------------------------------------------- Wikidata

def resolver(concepto: str, http: httpx.Client | None = None, cache: dict | None = None) -> str | None:
    """Concepto -> Q-id (en español). Devuelve None si no se puede resolver: no se inventa."""
    concepto = (concepto or "").strip().lower()
    if not concepto:
        return None
    cache = cache if cache is not None else _leer_cache()
    if concepto in cache["conceptos"]:
        return cache["conceptos"][concepto] or None

    cerrar = http is None
    cliente = http or httpx.Client(headers=CABECERAS, timeout=25.0)
    qid = None
    try:
        r = cliente.get(WIKIDATA_API, params={
            "action": "wbsearchentities", "search": concepto, "language": "es",
            "uselang": "es", "limit": 3, "format": "json"})
        if r.status_code == 200:
            resultados = r.json().get("search") or []
            qid = resultados[0]["id"] if resultados else None
    except Exception as e:
        log.warning("Wikidata no resolvió «%s»: %s", concepto, e)
        return None
    finally:
        if cerrar:
            cliente.close()

    cache["conceptos"][concepto] = qid or ""
    _guardar_cache(cache)
    return qid


def _entidades(ids: list[str], http: httpx.Client | None = None, cache: dict | None = None) -> dict:
    """Etiquetas (es/pt/en) y primer padre P279 de hasta 50 entidades por petición."""
    cache = cache if cache is not None else _leer_cache()
    faltantes = [i for i in ids if i not in cache["cadenas"]]
    if faltantes:
        cerrar = http is None
        cliente = http or httpx.Client(headers=CABECERAS, timeout=30.0)
        try:
            for i in range(0, len(faltantes), 50):
                lote = faltantes[i:i + 50]
                r = cliente.get(WIKIDATA_API, params={
                    "action": "wbgetentities", "ids": "|".join(lote),
                    "props": "labels|claims", "languages": "es|pt|en", "format": "json"})
                for qid, entidad in ((r.json().get("entities") or {}) if r.status_code == 200 else {}).items():
                    etiquetas = {k: v.get("value") for k, v in (entidad.get("labels") or {}).items()}
                    padre = None
                    for claim in (entidad.get("claims", {}).get("P279") or []):
                        try:
                            padre = claim["mainsnak"]["datavalue"]["value"]["id"]
                            break
                        except Exception:
                            continue
                    cache["cadenas"][qid] = {"etiquetas": etiquetas, "padre": padre}
                # Solo se auto-limita cuando el cliente lo creamos nosotros: quien inyecta el
                # suyo ya decide su propia política de cortesía (y así las pruebas no duermen).
                if cerrar:
                    time.sleep(0.15)
        except Exception as e:
            log.warning("Wikidata wbgetentities falló: %s", e)
        finally:
            if cerrar:
                cliente.close()
        _guardar_cache(cache)
    return {i: cache["cadenas"].get(i, {}) for i in ids}


def cadena(concepto_o_qid: str, niveles: int = NIVELES, http: httpx.Client | None = None,
           cache: dict | None = None) -> list[dict]:
    """Cadena de `subclase de` siguiendo el PRIMER padre (el «primer enlace», explícito).

    Devuelve el trayecto: ``[{"qid", "es", "pt", "en"}, ...]``. El último elemento es el nodo
    donde la cadena se detiene (la raíz del grafo, que **no** es una disciplina).
    """
    cache = cache if cache is not None else _leer_cache()
    qid = concepto_o_qid if str(concepto_o_qid).startswith("Q") else resolver(concepto_o_qid, http, cache)
    if not qid:
        return []

    trayecto = []
    visto = set()
    actual = qid
    for _ in range(niveles):
        if not actual or actual in visto:
            break
        visto.add(actual)
        datos = _entidades([actual], http, cache).get(actual) or {}
        etiquetas = datos.get("etiquetas") or {}
        trayecto.append({"qid": actual, "es": etiquetas.get("es"), "pt": etiquetas.get("pt"),
                         "en": etiquetas.get("en")})
        actual = datos.get("padre")
    return trayecto


# ---------------------------------------------------------------- guardián

def concentracion_por_nivel(conceptos: list[str], http: httpx.Client | None = None,
                            cache: dict | None = None) -> list[dict]:
    """Para cada nivel, cuántos nodos distintos aparecen y qué fracción concentra el mayor.

    Es el guardián anti-contaminación: un nivel que se lo traga todo no discrimina.
    """
    cache = cache if cache is not None else _leer_cache()
    trayectos = {c: cadena(c, NIVELES, http, cache) for c in conceptos}
    informe = []
    for nivel in range(NIVELES):
        nodos = Counter()
        etiqueta_de = {}
        for concepto, trayecto in trayectos.items():
            if len(trayecto) > nivel:
                qid = trayecto[nivel]["qid"]
                nodos[qid] += 1
                etiqueta_de[qid] = (trayecto[nivel].get("es") or trayecto[nivel].get("en")
                                    or trayecto[nivel].get("pt") or qid)
        total = sum(nodos.values())
        if not total:
            informe.append({"nivel": nivel + 1, "nodos": 0, "mayor": 0,
                            "concentracion": None, "utilizable": False, "etiqueta_mayor": None})
            continue
        qid_top, n_top = nodos.most_common(1)[0]
        concentracion = n_top / total
        etiqueta_top = etiqueta_de.get(qid_top) or ""
        # Doble criterio: reparte Y **ningún** nodo del nivel es una categoría de la ontología
        # superior. Se comprueban todos, no solo el dominante: medido en vivo, «ocurrencia»
        # aparecía como uno más entre cinco nodos y el nivel pasaba el filtro por concentración.
        ontologicas = sorted({etiqueta_de[q] for q in nodos
                              if norm(etiqueta_de.get(q) or "") in _ONTOLOGICAS_NORM})
        informe.append({
            "nivel": nivel + 1,
            "nodos": len(nodos),
            "mayor": n_top,
            "concentracion": round(concentracion, 3),
            "utilizable": (len(nodos) >= MIN_NODOS and concentracion < UMBRAL_CONCENTRACION
                           and not ontologicas),
            "etiqueta_mayor": etiqueta_top or None,
            "ontologicas": ontologicas,
        })
    return informe


def disciplina_de(conceptos: list[str], http: httpx.Client | None = None,
                  cache: dict | None = None) -> dict:
    """Disciplina derivada de un conjunto de conceptos, **con el guardián aplicado**.

    Elige el nivel **más profundo que sigue repartiendo**. Si ningún nivel discrimina, lo
    declara en vez de devolver una disciplina que no informa (nunca la raíz del grafo).

    Devuelve ``nivel_usado`` (None si no aplica), ``nodos`` en ese nivel, la ``trayectoria``
    por concepto y el ``motivo`` de la decisión en lenguaje llano.
    """
    conceptos = [c.strip().lower() for c in (conceptos or []) if str(c).strip()]
    if not conceptos:
        return {"nivel_usado": None, "nodos": {}, "trayectoria": {}, "concentracion": None,
                "motivo": "sin conceptos que analizar"}

    cache = cache if cache is not None else _leer_cache()
    niveles = concentracion_por_nivel(conceptos, http, cache)
    # Solo se consideran niveles que describan DISCIPLINAS: la sonda midió que por encima de
    # los primeros niveles la cadena entra en la ontología superior de Wikidata.
    usables = [f for f in niveles
               if f["utilizable"] and f["nivel"] <= NIVEL_MAXIMO_DISCIPLINA]
    trayectos = {c: cadena(c, NIVELES, http, cache) for c in conceptos}

    if not usables:
        descartados = [f for f in niveles if f["concentracion"] is not None and not f["utilizable"]]
        onto = [f["nivel"] for f in niveles if f.get("ontologica")]
        motivos = []
        if len(descartados) == len([f for f in niveles if f["concentracion"] is not None]):
            motivos.append("ningún nivel reparte con <50 % en un nodo")
        if onto:
            motivos.append(f"los niveles {onto} caen en categorías de la ontología superior "
                           f"(«entidad», «fenómeno»…), no en disciplinas")
        if not motivos:
            motivos.append(f"ningún nivel hasta {NIVEL_MAXIMO_DISCIPLINA} resultó utilizable")
        return {
            "nivel_usado": None, "nodos": {}, "trayectoria": trayectos, "concentracion": None,
            "sin_resolver": [c for c, t in trayectos.items() if not t],
            "motivo": "; ".join(motivos) + ". La disciplina no se deriva para no contaminar.",
        }

    elegido = max(usables, key=lambda f: f["nivel"])
    nodos: Counter = Counter()
    for concepto, trayecto in trayectos.items():
        if len(trayecto) >= elegido["nivel"]:
            datos = trayecto[elegido["nivel"] - 1]
            nombre = datos.get("es") or datos.get("en") or datos.get("pt") or datos["qid"]
            nodos[nombre] += 1

    return {
        "nivel_usado": elegido["nivel"],
        "concentracion": elegido["concentracion"],
        "nodos": dict(nodos.most_common()),
        "trayectoria": trayectos,
        "sin_resolver": [c for c, t in trayectos.items() if not t],
        "motivo": (f"nivel {elegido['nivel']} de la taxonomía: {elegido['nodos']} nodos, "
                   f"el mayor concentra {elegido['concentracion'] * 100:.0f} %"),
    }
