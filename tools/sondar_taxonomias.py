"""SONDA DE TAXONOMÍAS: ¿sirve un vocabulario jerárquico existente para clasificar por disciplina?

Mide los dos candidatos sobre conceptos REALES del corpus y decide con datos:

  * **OpenAlex** — `primary_topic` -> subfield -> field -> domain (4 niveles, ya accesible).
  * **Wikidata**  — cadena `subclase de` (P279) siguiendo el PRIMER padre, que es exactamente
    el fenómeno del «primer enlace» que llega a Filosofía, pero con la relación explícita.

**Guardián anti-contaminación (la lección del fantasma `comunicacion`):** un nodo que se traga
todos los conceptos no sirve como disciplina. Para cada nivel se mide cuántos nodos distintos
aparecen y qué fracción concentra el mayor. Un nivel solo es **utilizable** si reparte
(> 1 nodo distinto y el mayor concentra < 50 %).

USO:
    python tools/sondar_taxonomias.py
SALIDA:
    data/demo/sonda_taxonomias.json + informe en consola
"""
from __future__ import annotations

import io
import json
import sys
import time
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))

import httpx  # noqa: E402

DEMO = RAIZ / "data" / "demo"
CABECERAS = {"User-Agent": "Thinkuy/0.3 (radar academico abierto; contacto@thinkuy.dev)"}
OPENALEX_TOPICS = "https://api.openalex.org/topics"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

NIVELES_WIKIDATA = 10
UMBRAL_CONCENTRACION = 0.50  # si un nodo se lleva más de esto, el nivel no discrimina

# Conceptos reales: palabras clave del corpus + términos multipalabra + el caso clínico que
# falló + el eje epistémico del proyecto. Nada inventado.
CONCEPTOS = [
    # comunicación y política (del corpus)
    "comunicación", "journalism", "disinformation", "narrative", "politics", "democracy",
    "ideology", "hegemony", "social media", "political science", "public relations",
    "semiotics", "curriculum", "educación",
    # métricas y ciencia abierta
    "altmetrics", "bibliometrics", "citation", "scopus", "citizen science",
    # salud y ciencias naturales (para probar el cruce de dominio)
    "pandemic", "covid-19", "perception", "biodiversity", "sustainability",
    "inteligencia artificial",
    # el caso clínico que devolvía cero
    "miocarditis", "cáncer de riñón", "percepción de salud",
    # eje epistémico del proyecto
    "filosofía", "epistemología", "decolonial", "ecología de saberes", "educación popular",
    # extremos previsibles
    "turismo", "instagram", "elecciones", "creatividad", "gobernanza",
]


def openalex_de(concepto: str, http: httpx.Client) -> dict | None:
    """Tema de OpenAlex más afín y su ruta completa hasta el dominio."""
    try:
        r = http.get(OPENALEX_TOPICS, params={"search": concepto, "per-page": 1}, timeout=25.0)
        if r.status_code != 200:
            return None
        resultados = r.json().get("results") or []
        if not resultados:
            return None
        t = resultados[0]
        return {
            "nivel_1_tema": t.get("display_name"),
            "nivel_2_subcampo": (t.get("subfield") or {}).get("display_name"),
            "nivel_3_campo": (t.get("field") or {}).get("display_name"),
            "nivel_4_dominio": (t.get("domain") or {}).get("display_name"),
        }
    except Exception:
        return None


def wikidata_qid(concepto: str, http: httpx.Client) -> str | None:
    """Resuelve el concepto a un Q-id en español."""
    try:
        r = http.get(WIKIDATA_API, params={
            "action": "wbsearchentities", "search": concepto, "language": "es",
            "uselang": "es", "limit": 3, "format": "json"}, timeout=25.0)
        resultados = r.json().get("search") or []
        return resultados[0]["id"] if resultados else None
    except Exception:
        return None


def _entidades(http: httpx.Client, ids: list[str]) -> dict:
    """Etiquetas y primer padre P279 de hasta 50 entidades por petición."""
    salida: dict = {}
    for i in range(0, len(ids), 50):
        lote = ids[i:i + 50]
        try:
            r = http.get(WIKIDATA_API, params={
                "action": "wbgetentities", "ids": "|".join(lote),
                "props": "labels|claims", "languages": "es|pt|en", "format": "json"}, timeout=30.0)
            salida.update(r.json().get("entities") or {})
        except Exception:
            continue
        time.sleep(0.15)
    return salida


def wikidata_cadenas(qids: dict[str, str], niveles: int, http: httpx.Client) -> list[dict]:
    """Sigue el PRIMER padre P279 de cada concepto, nivel a nivel (como el «primer enlace»).

    Devuelve, por nivel, el nodo en el que queda cada concepto, con sus etiquetas es/pt/en.
    """
    actual = dict(qids)  # concepto -> qid actual
    por_nivel: list[dict] = []
    for _ in range(niveles):
        ids = sorted(set(actual.values()))
        if not ids:
            break
        entidades = _entidades(http, ids)
        nivel: dict = {}
        siguiente: dict = {}
        for concepto, qid in actual.items():
            e = entidades.get(qid) or {}
            etiquetas = {k: v.get("value") for k, v in (e.get("labels") or {}).items()}
            nivel[concepto] = {"qid": qid, "etiquetas": etiquetas}
            padre = None
            for claim in (e.get("claims", {}).get("P279") or []):
                try:
                    padre = claim["mainsnak"]["datavalue"]["value"]["id"]
                    break
                except Exception:
                    continue
            if padre:
                siguiente[concepto] = padre
        por_nivel.append(nivel)
        actual = siguiente
    return por_nivel


def analizar_colapso(mapeo_por_nivel: list[dict]) -> list[dict]:
    """Para cada nivel: cuántos nodos distintos y qué fracción concentra el mayor."""
    informe = []
    for indice, nivel in enumerate(mapeo_por_nivel):
        nodos = Counter(v["qid"] for v in nivel.values() if v.get("qid"))
        total = sum(nodos.values())
        if not total:
            informe.append({"nivel": indice + 1, "nodos": 0, "mayor": 0, "concentracion": None,
                            "utilizable": False, "ejemplo": None})
            continue
        qid_top, n_top = nodos.most_common(1)[0]
        ejemplo = next((v["etiquetas"].get("es") or v["etiquetas"].get("en")
                        or v["etiquetas"].get("pt") for v in nivel.values()
                        if v.get("qid") == qid_top), None)
        concentracion = n_top / total
        informe.append({
            "nivel": indice + 1,
            "nodos": len(nodos),
            "mayor": n_top,
            "concentracion": round(concentracion, 3),
            "utilizable": len(nodos) > 1 and concentracion < UMBRAL_CONCENTRACION,
            "ejemplo": ejemplo,
        })
    return informe


def main() -> None:
    http = httpx.Client(headers=CABECERAS, follow_redirects=True, timeout=40.0)
    resultado = {"conceptos": CONCEPTOS, "openalex": [], "wikidata": [], "wikidata_cadenas": {}}

    print("=" * 104)
    print(f"SONDA DE TAXONOMÍAS — {len(CONCEPTOS)} conceptos reales del corpus")
    print("=" * 104)

    # ── OpenAlex ────────────────────────────────────────────────────────────
    t0 = time.time()
    resueltos_oa = 0
    mapeo_oa: dict[int, dict] = {1: {}, 2: {}, 3: {}, 4: {}}
    for concepto in CONCEPTOS:
        fila = openalex_de(concepto, http)
        if fila:
            resueltos_oa += 1
            for nivel, clave in ((1, "nivel_1_tema"), (2, "nivel_2_subcampo"),
                                 (3, "nivel_3_campo"), (4, "nivel_4_dominio")):
                if fila.get(clave):
                    mapeo_oa[nivel][concepto] = {"qid": fila[clave], "etiquetas": {"es": fila[clave]}}
        resultado["openalex"].append({"concepto": concepto, **({} if not fila else fila)})
        time.sleep(0.1)
    segundos_oa = time.time() - t0

    # ── Wikidata ────────────────────────────────────────────────────────────
    t0 = time.time()
    qids: dict[str, str] = {}
    sin_qid = []
    for concepto in CONCEPTOS:
        qid = wikidata_qid(concepto, http)
        if qid:
            qids[concepto] = qid
        else:
            sin_qid.append(concepto)
        time.sleep(0.1)
    cadenas = wikidata_cadenas(qids, NIVELES_WIKIDATA, http)
    segundos_wd = time.time() - t0

    for nivel in cadenas:
        for concepto, dato in nivel.items():
            resultado["wikidata_cadenas"].setdefault(concepto, []).append({
                "qid": dato["qid"], "es": dato["etiquetas"].get("es"),
                "pt": dato["etiquetas"].get("pt"), "en": dato["etiquetas"].get("en")})

    # ── Informe: OpenAlex ───────────────────────────────────────────────────
    print()
    print("A) OpenAlex — primary_topic -> subfield -> field -> domain")
    print("-" * 104)
    print(f"  resueltos: {resueltos_oa}/{len(CONCEPTOS)} · {segundos_oa:.1f} s "
          f"({segundos_oa / len(CONCEPTOS):.2f} s por concepto)")
    colapso_oa = analizar_colapso([mapeo_oa[n] for n in (1, 2, 3, 4)])
    print(f"  {'nivel':<34} {'nodos':>6} {'mayor':>6} {'concentra':>10} {'¿utilizable?':>13}")
    etiquetas_oa = {1: "1. Tema (primario)", 2: "2. Subcampo", 3: "3. Campo", 4: "4. Dominio"}
    for fila in colapso_oa:
        marca = "SÍ" if fila["utilizable"] else "no"
        print(f"  {etiquetas_oa[fila['nivel']]:<34} {fila['nodos']:>6} {fila['mayor']:>6} "
              f"{(fila['concentracion'] or 0) * 100:>9.0f}% {marca:>13}   {fila['ejemplo'] or ''}")
    resultado["openalex_colapso"] = colapso_oa

    # ── Informe: Wikidata ───────────────────────────────────────────────────
    print()
    print("B) Wikidata — cadena `subclase de` siguiendo el primer padre")
    print("-" * 104)
    print(f"  resueltos: {len(qids)}/{len(CONCEPTOS)} · sin Q-id: {sin_qid or 'ninguno'} · "
          f"{segundos_wd:.1f} s")
    colapso_wd = analizar_colapso(cadenas)
    print(f"  {'nivel':<34} {'nodos':>6} {'mayor':>6} {'concentra':>10} {'¿utilizable?':>13}  ejemplo")
    for fila in colapso_wd:
        marca = "SÍ" if fila["utilizable"] else "no"
        print(f"  {'nivel ' + str(fila['nivel']):<34} {fila['nodos']:>6} {fila['mayor']:>6} "
              f"{(fila['concentracion'] or 0) * 100:>9.0f}% {marca:>13}  {fila['ejemplo'] or ''}")
    resultado["wikidata_colapso"] = colapso_wd

    # ── Cobertura de etiquetas ──────────────────────────────────────────────
    print()
    print("C) Cobertura de etiquetas en Wikidata (crítico para el nicho ES/PT)")
    print("-" * 104)
    total_nodos = es = pt = en = 0
    for fila in cadenas:
        for dato in fila.values():
            total_nodos += 1
            es += 1 if dato["etiquetas"].get("es") else 0
            pt += 1 if dato["etiquetas"].get("pt") else 0
            en += 1 if dato["etiquetas"].get("en") else 0
    if total_nodos:
        print(f"  nodos en las cadenas: {total_nodos}")
        print(f"    con etiqueta ES: {es:>5} ({100 * es / total_nodos:.0f} %)")
        print(f"    con etiqueta PT: {pt:>5} ({100 * pt / total_nodos:.0f} %)")
        print(f"    con etiqueta EN: {en:>5} ({100 * en / total_nodos:.0f} %)")
    resultado["etiquetas_wikidata"] = {"nodos": total_nodos, "es": es, "pt": pt, "en": en}

    # ── Cadena de ejemplo ───────────────────────────────────────────────────
    print()
    print("D) La cadena completa de un concepto (el «trayecto», no el destino)")
    print("-" * 104)
    for ejemplo in ("miocarditis", "periodismo", "biodiversity"):
        cadena = resultado["wikidata_cadenas"].get(ejemplo)
        if not cadena:
            continue
        etiquetas = [c.get("es") or c.get("en") or c["qid"] for c in cadena]
        print(f"  {ejemplo}: " + " -> ".join(str(e) for e in etiquetas[:NIVELES_WIKIDATA]))

    http.close()
    DEMO.mkdir(parents=True, exist_ok=True)
    (DEMO / "sonda_taxonomias.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetalle: data/demo/sonda_taxonomias.json")


if __name__ == "__main__":
    main()
