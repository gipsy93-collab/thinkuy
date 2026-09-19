"""Opción A2 — SELECCIÓN de postura por LLM, con etiqueta asignada por tabla.

Principio de diseño (Hito 32): el modelo hace lo que sabe hacer (reconocer y SELECCIONAR el
fragmento que expresa postura); la ETIQUETA la sigue poniendo la tabla cerrada de marcadores.
Así el juicio queda acotado y auditable:

    1. El LLM decide si el autor que cita toma postura y devuelve el SPAN MÍNIMO VERBATIM.
    2. Guardián duro: el span debe ser una subcadena literal de la oración. Si no, se rechaza.
    3. La tabla cerrada asigna `posible consenso` / `posible disenso` al span.
    4. Si el span no tiene marcador en la tabla -> `POSTURA_SIN_MARCADOR`: candidato a
       ampliar el lexicón tras validación humana.

Configuración (endpoint compatible con OpenAI):
    $env:THINKUY_LLM_API   = "https://api.deepseek.com/v1"   # o openrouter, groq, openai...
    $env:THINKUY_LLM_MODEL = "deepseek-chat"
    $env:THINKUY_LLM_KEY   = "sk-..."

USO:
    python tools/seleccion_postura_api.py --area medicina-social --max 30
    python tools/seleccion_postura_api.py --area medicina-social --max 3 --dry-run

SALIDAS:
    data/dataset_v4/seleccion_postura_llm.jsonl     (resultado estructurado)
    data/dataset_v4/cache_llm_seleccion.jsonl       (caché: re-ejecutar no vuelve a pagar)
    data/demo/SELECCION_POSTURA_<area>.md           (hoja de revisión para el investigador)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import httpx  # noqa: E402

from backend.radar.text_extractor import (  # noqa: E402
    extract_citation_contexts,
    extract_numeric_citation_contexts,
    parse_reference_entry,
)
from etiquetador_determinista import detectar_marcadores, norm, oracion_util  # noqa: E402

D = PROJECT_ROOT / "data" / "dataset_v4"
DEMO = PROJECT_ROOT / "data" / "demo"

API = os.environ.get("THINKUY_LLM_API", "").rstrip("/")
MODEL = os.environ.get("THINKUY_LLM_MODEL", "")
KEY = os.environ.get("THINKUY_LLM_KEY", "")

SISTEMA = (
    "Eres un anotador lingüístico. Tu única tarea es decidir si el AUTOR QUE CITA toma postura "
    "sobre la OBRA CITADA y, si la toma, devolver el fragmento mínimo VERBATIM que la expresa.\n"
    "Reglas estrictas:\n"
    "- El span debe estar COPIADO LITERALMENTE de la oración. No parafrasees ni corrijas.\n"
    "- Si el autor solo informa, describe, menciona o adopta un método sin evaluar, NO hay postura.\n"
    "- Caso clave: «García (2020) demostró que X» NO es postura del que cita: es un reporte.\n"
    "- «Nuestros resultados corroboran a García» SÍ es postura (apoyo).\n"
    "- «A diferencia de López, nuestros datos no replican el efecto» SÍ es postura (disenso).\n"
    "- Si no hay postura, span = null.\n"
    'Devuelve SOLO este JSON: {"hay_postura": true|false, "span": "fragmento literal"|null, '
    '"razon": "máximo 12 palabras"}'
)


def usuario(citado: str, oracion: str, contexto: str) -> str:
    return (
        f"OBRA CITADA: {citado}\n\n"
        f"ORACIÓN:\n{oracion}\n\n"
        f"CONTEXTO INMEDIATO:\n{contexto[:500]}"
    )


def clave_cache(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]


def cargar_cache() -> dict[str, dict]:
    p = D / "cache_llm_seleccion.jsonl"
    if not p.exists():
        return {}
    out = {}
    for l in p.read_text(encoding="utf-8").splitlines():
        if l.strip():
            try:
                r = json.loads(l)
                out[r["clave"]] = r
            except Exception:
                pass
    return out


def llamar_api(prompt_usuario: str, timeout: float = 60.0) -> dict | None:
    if not API:
        raise RuntimeError("Falta THINKUY_LLM_API (endpoint compatible con OpenAI).")
    cuerpo = {
        "model": MODEL or "gpt-4o-mini",
        "messages": [{"role": "system", "content": SISTEMA},
                     {"role": "user", "content": prompt_usuario}],
        "temperature": 0.0,
        "max_tokens": 300,
        "stream": False,
    }
    cabeceras = {"Content-Type": "application/json"}
    if KEY:
        cabeceras["Authorization"] = f"Bearer {KEY}"
    r = httpx.post(f"{API}/chat/completions", json=cuerpo, timeout=timeout, headers=cabeceras)
    if r.status_code >= 400:
        detalle = ""
        try:
            detalle = r.json().get("error", {}).get("message") or ""
        except Exception:
            detalle = r.text[:200]
        raise RuntimeError(f"API {r.status_code}: {detalle}")
    contenido = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", contenido, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def citas_de(rec: dict) -> list[tuple[dict, dict]]:
    sect = rec.get("sections") or {}
    cuerpo = "\n\n".join(v for k, v in sect.items() if k != "references" and v)
    if len(cuerpo) < 2000:
        return []
    refs = [parse_reference_entry(r) for r in (rec.get("references") or [])[:200]]
    refs = [r for r in refs if r and (r.get("author") or r.get("doi"))]
    vistos, salida = set(), []
    for pr in refs[:60]:
        for ctx in extract_citation_contexts(cuerpo, cited_doi=pr.get("doi") or "",
                                             cited_author=pr.get("author"), cited_year=pr.get("year")):
            k = norm(ctx.get("sentence", ""))[:70]
            if k and k not in vistos:
                vistos.add(k)
                salida.append((ctx, pr))
    for ctx in extract_numeric_citation_contexts(cuerpo, rec.get("references") or []):
        k = norm(ctx.get("sentence", ""))[:70]
        if k and k not in vistos:
            vistos.add(k)
            salida.append((ctx, {"author": ctx.get("cited_author"), "year": ctx.get("cited_year")}))
    return salida


def etiqueta_por_tabla(span: str) -> tuple[str, list[str]]:
    """La clase la pone la TABLA CERRADA, nunca el LLM."""
    hit = detectar_marcadores(norm(span), "A")
    if "SUPPORT" in hit and "CONFLICT" in hit:
        return "AMBIGUO", hit.get("SUPPORT", []) + hit.get("CONFLICT", [])
    if "SUPPORT" in hit:
        return "SUPPORT", hit["SUPPORT"]
    if "CONFLICT" in hit:
        return "CONFLICT", hit["CONFLICT"]
    # Los concesivos (`si bien`, `while`, `though`, `aunque`) expresan una posición parcial:
    # reconocen algo y lo limitan. Tienen etiqueta propia en lugar de caer en "sin marcador".
    if "CONCESSION" in hit:
        return "CONCESION", hit["CONCESSION"]
    return "POSTURA_SIN_MARCADOR", []


def respuesta_simulada(c: dict) -> dict:
    """Simulador local para validar la plomería SIN pagar API.

    Devuelve el fragmento (cláusula) que contiene un marcador de la tabla, si existe.
    Ejercita las dos ramas (con y sin postura) y los guardianes.
    """
    oracion = c["oracion"]
    for m in re.finditer(r"[^.;!?]+[.;!?]?", oracion):
        frag = m.group(0).strip()
        hit = detectar_marcadores(norm(frag), "A")
        if hit:
            return {"hay_postura": True, "span": frag, "razon": "simulado: marcador en la cláusula"}
    return {"hay_postura": False, "span": None, "razon": "simulado: sin marcador"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="medicina-social")
    ap.add_argument("--max", type=int, default=30, help="Máximo de citas a enviar (control de coste)")
    ap.add_argument("--dry-run", action="store_true", help="Muestra los prompts sin llamar a la API")
    ap.add_argument("--simular", action="store_true", help="Ejercita toda la plomería sin llamar a la API")
    ap.add_argument("--respuestas", type=str, default="", help="JSONL con respuestas ya listas "
                    "(clave, hay_postura, span, razon): modo 'modelo manual', sin API")
    ap.add_argument("--volcar", type=str, default="", help="Escribe los candidatos con su clave de caché "
                    "y termina (para que un humano/asistente haga de modelo)")
    ap.add_argument("--pausa", type=float, default=0.4, help="Segundos entre llamadas")
    args = ap.parse_args()

    inv = json.loads((PROJECT_ROOT / "data" / "corpus_v2" / "inventario_unicos.json").read_text(encoding="utf-8"))
    articulos = [x for x in inv["unicos"] if x["area"] == args.area and x["usabilidad"]["T3"]]

    candidatos = []
    for x in articulos:
        for ctx, pr in citas_de(x):
            oracion = ctx.get("sentence", "")
            util, _ = oracion_util(oracion)
            if not util:
                continue
            citado = f"{pr.get('author') or '¿?'} ({pr.get('year') or 's.f.'})"
            candidatos.append({"doi": x["doi_filename"], "idioma": x["idioma"], "citado": citado,
                               "oracion": " ".join(oracion.split()), "contexto": " ".join((ctx.get("paragraph") or "").split())})
    candidatos = candidatos[: args.max]
    print(f"Candidatos a enviar: {len(candidatos)} (de {args.area})")

    if args.volcar:
        destino = Path(args.volcar)
        if not destino.is_absolute():
            destino = PROJECT_ROOT / destino
        with open(destino, "w", encoding="utf-8") as fh:
            for c in candidatos:
                fh.write(json.dumps({**c, "clave": clave_cache(c["oracion"] + "|" + c["citado"])},
                                    ensure_ascii=False) + "\n")
        print(f"Volcados {len(candidatos)} candidatos con su clave -> {destino}")
        print("Siguiente paso: producir un JSONL de respuestas {clave, hay_postura, span, razon} "
              "y ejecutar con --respuestas")
        return

    if args.dry_run:
        for c in candidatos[:2]:
            print("\n" + "-" * 74)
            print("SISTEMA:\n" + SISTEMA)
            print("\nUSUARIO:\n" + usuario(c["citado"], c["oracion"], c["contexto"]))
        print("\n(dry-run: no se llamó a la API)")
        return

    if not API and not args.simular and not args.respuestas:
        print("\nFALTA CONFIGURACIÓN. Define antes de ejecutar:")
        print('  $env:THINKUY_LLM_API   = "https://api.deepseek.com/v1"   # o openrouter/groq/openai')
        print('  $env:THINKUY_LLM_MODEL = "deepseek-chat"')
        print('  $env:THINKUY_LLM_KEY   = "sk-..."')
        return

    cache = cargar_cache()
    # Modo "modelo manual": las respuestas vienen de un archivo (las escribió el investigador
    # o el asistente haciendo de modelo). No se llama a ninguna API.
    manuales: dict[str, dict] = {}
    if args.respuestas:
        rp = Path(args.respuestas)
        if not rp.is_absolute():
            rp = PROJECT_ROOT / rp
        if not rp.exists():
            print(f"No existe el archivo de respuestas: {rp}")
            return
        for l in rp.read_text(encoding="utf-8").splitlines():
            if l.strip():
                try:
                    r = json.loads(l)
                    manuales[r["clave"]] = r
                except Exception:
                    pass
        print(f"Modo MODELO MANUAL: {len(manuales)} respuestas cargadas desde {rp.name}")

    resultados, errores, faltantes = [], 0, []
    cache_fh = open(D / "cache_llm_seleccion.jsonl", "a", encoding="utf-8")
    for i, c in enumerate(candidatos, 1):
        k = clave_cache(c["oracion"] + "|" + c["citado"])
        if k in manuales:
            r = dict(manuales[k])
        elif k in cache:
            r = dict(cache[k])
        elif args.simular:
            r = respuesta_simulada(c)
        elif args.respuestas:
            faltantes.append(c)
            continue
        else:
            try:
                r = llamar_api(usuario(c["citado"], c["oracion"], c["contexto"]))
            except Exception as e:
                errores += 1
                print(f"[{i:03d}/{len(candidatos)}] ERROR {e}")
                time.sleep(1.0)
                continue
            time.sleep(args.pausa)
            if r is None:
                errores += 1
                continue
            cache_fh.write(json.dumps({"clave": k, **r}, ensure_ascii=False) + "\n")
            cache_fh.flush()
            r = dict(r)
        # ── Guardianes ──
        hay = bool(r.get("hay_postura"))
        span = (r.get("span") or "").strip()
        veredicto, marcadores = "NO_POSTURA", []
        if hay:
            if not span:
                veredicto = "RECHAZADO_SIN_SPAN"
            elif span not in c["oracion"]:
                veredicto = "RECHAZADO_NO_VERBATIM"
            else:
                clase, marcadores = etiqueta_por_tabla(span)
                veredicto = clase
        resultados.append({**c, "hay_postura": hay, "span": span, "razon": r.get("razon", ""),
                           "veredicto": veredicto, "marcadores_tabla": marcadores})
        icono = {"NO_POSTURA": "·", "RECHAZADO_NO_VERBATIM": "!", "RECHAZADO_SIN_SPAN": "!"}.get(veredicto, "+")
        print(f"[{i:03d}/{len(candidatos)}] {icono} {veredicto:22} | {c['citado'][:24]:24} | {(span or c['oracion'])[:60]}")
    cache_fh.close()

    with open(D / "seleccion_postura_llm.jsonl", "w", encoding="utf-8") as fh:
        for r in resultados:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    conteo = Counter(r["veredicto"] for r in resultados)
    sin_marcador = [r for r in resultados if r["veredicto"] == "POSTURA_SIN_MARCADOR"]

    # ── Hoja de revisión para el investigador ──
    lineas = [
        f"# Selección de postura asistida por LLM — área: {args.area}",
        "",
        "> El LLM **selecciona el fragmento**; la etiqueta la pone la **tabla cerrada de marcadores**. "
        "Verifica cada propuesta: la última columna es tuya.",
        "",
        f"**Modelo:** `{MODEL or '(sin especificar)'}` · **Candidatos enviados:** {len(candidatos)} · **Errores:** {errores}",
        "",
        "| Veredicto | n |",
        "| :--- | ---: |",
    ]
    for k, v in conteo.most_common():
        lineas.append(f"| `{k}` | {v} |")
    lineas += ["", "---", "", "## Propuestas con postura detectada", ""]
    for r in [x for x in resultados if x["veredicto"] in ("SUPPORT", "CONFLICT", "CONCESION", "AMBIGUO", "POSTURA_SIN_MARCADOR")]:
        etiqueta = {"SUPPORT": "posible consenso", "CONFLICT": "posible disenso",
                    "CONCESION": "posible concesión o matización",
                    "AMBIGUO": "señal mixta (revisar)",
                    "POSTURA_SIN_MARCADOR": "postura sin marcador en la tabla"}[r["veredicto"]]
        lineas += [
            f"### {etiqueta} — {r['citado']}",
            "",
            f"**Oración:** {r['oracion']}",
            "",
            f"**Fragmento propuesto:** «**{r['span']}**»",
            "",
            f"**Razón del modelo:** {r['razon']}",
            "",
            f"**Marcadores de la tabla:** {', '.join(f'`{m}`' for m in r['marcadores_tabla']) or '—'}",
            "",
            "**Tu verificación:** [ ] acepto   [ ] rechazo   [ ] cambiar etiqueta a: ______",
            "",
            "---",
            "",
        ]
    if sin_marcador:
        lineas += ["## Candidatos a ampliar el lexicón", "",
                   "Estos fragmentos expresan postura según el modelo pero **no contienen ningún marcador de la lista**. "
                   "Revisarlos es la vía más barata para crecer el lexicón (10 segundos cada uno).", ""]
        for r in sin_marcador:
            lineas.append(f"- «{r['span']}»  \n  - en: {r['oracion'][:150]}…")
    DEMO.mkdir(parents=True, exist_ok=True)
    (DEMO / f"SELECCION_POSTURA_{args.area}.md").write_text("\n".join(lineas), encoding="utf-8")

    print("\n" + "=" * 74)
    print(f"RESULTADO: {dict(conteo)}")
    print(f"Errores de API: {errores}")
    print(f"Candidatos a ampliar el lexicón: {len(sin_marcador)}")
    print(f"Hoja de revisión: {DEMO / f'SELECCION_POSTURA_{args.area}.md'}")
    print("=" * 74)


if __name__ == "__main__":
    main()
