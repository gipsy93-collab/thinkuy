"""Mide un servidor Kev (familia de modelos de decisión) sobre la muestra de control T3.

Qué hace
--------
Toma los 36 casos de `data/dataset_v4/control_36.tsv` + las etiquetas humanas de los
`pase*_*.csv`, le pregunta a un servidor Kev los tres ejes ortogonales de T3
(A postura · B certeza · C función) **sin afinar** (zero-shot), y calcula:

  - el kappa de Cohen de Kev contra el humano (la misma métrica del Gate 2),
  - el kappa del motor determinista contra el humano (leído de `gate2_resultado.json`,
    para no recalcularlo ni duplicar la fuente de verdad),
  - y las métricas de umbral de confianza: cuántas decisiones se podrían automatizar
    a un presupuesto de error dado, que es la razón de ser de Kev.

No toca el backend ni el catálogo. Es una sonda de medición.

Uso
---
    # 1. Levantar Kev en algún sitio (local, Modal, otro equipo):
    #    uv run --extra serve python -m kev.serve --run jaredpalmer/kev-0.8b --port 8009
    set KEV_BASE_URL=http://127.0.0.1:8009
    python tools/kev_eval.py                 # mide y escribe el informe
    python tools/kev_eval.py --dry-run       # imprime la petición de un caso y sale
    python tools/kev_eval.py --limit 5       # prueba corta

Variables de entorno
--------------------
    KEV_BASE_URL  (def. http://127.0.0.1:8009)
    KEV_MODEL     (def. kev-latest)
    KEV_API_KEY   (opcional; se envía como Authorization: Bearer)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
D = PROJECT_ROOT / "data" / "dataset_v4"

# Reutiliza la MISMA métrica y los MISMOS lectores que el Gate 2: una sola fuente de verdad.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from calcular_kappa import canon, kappa_cohen, leer_pases, leer_tsv  # noqa: E402

# --- Definición canónica de los tres ejes (idéntica al Plan V5 y a la interfaz) -----------
ETIQUETAS_A = ["SUPPORT", "CONFLICT", "NEUTRAL"]
ETIQUETAS_B = ["STRONG", "MODERATE", "WEAK", "NO_DECLARADA"]
ETIQUETAS_C = ["REPORT", "METHOD_ADOPTION", "GAP", "CONCESSION_REDEFINITION", "OWN_CLAIM"]

INSTRUCCIONES_A = (
    "¿Qué postura toma el trabajo que cita respecto de la fuente citada? "
    "SUPPORT: respalda, confirma o se apoya en ella. "
    "CONFLICT: la contradice, la cuestiona o matiza en contra. "
    "NEUTRAL: solo la reporta o menciona, sin tomar partido."
)
INSTRUCCIONES_B = (
    "¿Con qué fuerza se afirma lo citado? "
    "STRONG: afirmación categórica. "
    "MODERATE: afirmación con matices o atribuida a un tercero. "
    "WEAK: indicio, posibilidad o duda. "
    "NO_DECLARADA: el texto no marca fuerza."
)
INSTRUCCIONES_C = (
    "¿Qué función cumple la cita en el texto que la usa? "
    "REPORT: reporta un dato, resultado o antecedente. "
    "METHOD_ADOPTION: adopta un método, instrumento o definición. "
    "GAP: señala un vacío o ausencia. "
    "CONCESSION_REDEFINITION: concede algo y lo redefine. "
    "OWN_CLAIM: sostiene un planteamiento propio del autor."
)

DESCRIPCIONES_A = {
    "SUPPORT": "respalda, confirma o se apoya en la fuente citada",
    "CONFLICT": "contradice, cuestiona o matiza en contra",
    "NEUTRAL": "solo la reporta o menciona, sin tomar partido",
}
DESCRIPCIONES_B = {
    "STRONG": "afirmación categórica",
    "MODERATE": "afirmación con matices o atribuida a un tercero",
    "WEAK": "indicio, posibilidad o duda",
    "NO_DECLARADA": "el texto no marca fuerza",
}
DESCRIPCIONES_C = {
    "REPORT": "reporta un dato, resultado o antecedente",
    "METHOD_ADOPTION": "adopta un método, instrumento o definición",
    "GAP": "señala un vacío o ausencia",
    "CONCESSION_REDEFINITION": "concede algo y lo redefine",
    "OWN_CLAIM": "sostiene un planteamiento propio del autor",
}

# El estado se recorta a la ventana de contexto del motor (±300 caracteres ≈ lo de T3) y
# muy por debajo del techo de entrenamiento de Kev (~384 tokens), para no medir con ruido.
MAX_PARRAFO_CHARS = 800

UMBRALES_CONFIANZA = [0.6, 0.7, 0.8, 0.9]


# ---------------------------------------------------------------- construcción de la petición

def construir_estado(fila: dict) -> str:
    """Estado que ve Kev: la oración que cita + un tramo del párrafo donde vive."""
    oracion = (fila.get("oracion") or "").strip()
    parrafo = (fila.get("parrafo") or "").strip()[:MAX_PARRAFO_CHARS]
    return f"Oración que cita:\n{oracion}\n\nContexto:\n{parrafo}"


def construir_preguntas() -> dict:
    """Las tres preguntas de T3, independientes entre sí (Kev no las deja leerse).

    Cada opción lleva descripción: Laya la **exige** (rechaza `null` con HTTP 400) y a los
    otros motores no les estorba."""
    return {
        "A": {"type": "choice", "instructions": INSTRUCCIONES_A,
              "criteria": dict(DESCRIPCIONES_A)},
        "B": {"type": "choice", "instructions": INSTRUCCIONES_B,
              "criteria": dict(DESCRIPCIONES_B)},
        "C": {"type": "choice", "instructions": INSTRUCCIONES_C,
              "criteria": dict(DESCRIPCIONES_C)},
    }


def construir_peticion(fila: dict, model: str) -> dict:
    """Petición systemone. `model` se omite si va vacío: el servidor local de jev-style no lo
    necesita y así la misma sonda sirve para Kev, jev-style o cualquier servidor systemone."""
    req = {"state": construir_estado(fila), "questions": construir_preguntas()}
    if model:
        req["model"] = model
    return req


# ---------------------------------------------------------------- parseo de la respuesta

def canon_choice(valor: Any) -> str:
    """Normaliza la etiqueta devuelta por Kev a la forma canónica del proyecto."""
    return canon(str(valor or ""))


def parse_respuesta(payload: dict) -> dict[str, dict]:
    """De la respuesta systemone extrae, por pregunta, la etiqueta elegida y **la probabilidad
    de ESA respuesta** (no una fórmula de confianza distinta por motor).

    Motivo medido: cada motor define `confidence` a su manera —Kev/Jev-Style usan
    `(k·p_max−1)/(k−1)`, Laya usa `1 − entropía normalizada`— así que un umbral no es
    comparable entre ellos. `answer_confidence` (Laya) y `max(probabilities)` sí son, en todos,
    la probabilidad calibrada de la respuesta reportada, que es lo que se compara contra un
    presupuesto de error. Nunca inventa: lo que no viene, se cuenta como fallo más arriba."""
    out: dict[str, dict] = {}
    for qid, ans in (payload or {}).get("answers", {}).items():
        if not isinstance(ans, dict) or ans.get("type") != "choice":
            continue
        etiqueta = canon_choice(ans.get("choice"))
        if not etiqueta:
            continue
        probs = ans.get("probabilities") or {}
        conf = ans.get("answer_confidence")
        if conf is None:
            conf = max(probs.values()) if probs else ans.get("confidence", 0.0)
        out[qid] = {"etiqueta": etiqueta, "confianza": float(conf), "probabilidades": probs}
    return out


# ---------------------------------------------------------------- métricas

def metricas_por_umbral(registros: list[dict]) -> dict[str, dict]:
    """Para cada umbral de confianza: cuánto se automatizaría y con qué exactitud.

    `registros` son dicts con `correcto` (bool) y `confianza` (float). Devuelve, por umbral,
    la cobertura (fracción automatizable), la exactitud entre las cubiertas y los errores.
    Un umbral con exactitud < 0.95 no cumple el presupuesto de error del 5 %."""
    metricas: dict[str, dict] = {}
    n = len(registros)
    for t in UMBRALES_CONFIANZA:
        cubiertas = [r for r in registros if r["confianza"] >= t]
        aciertos = sum(1 for r in cubiertas if r["correcto"])
        exactitud = (aciertos / len(cubiertas)) if cubiertas else None
        metricas[f"{t:.1f}"] = {
            "cobertura": round(len(cubiertas) / n, 4) if n else None,
            "n_cubiertas": len(cubiertas),
            "exactitud": round(exactitud, 4) if exactitud is not None else None,
            "errores": len(cubiertas) - aciertos,
            "cumple_presupuesto_5pct": bool(exactitud is not None and exactitud >= 0.95),
        }
    return metricas


def _baseline_motor(path: Path) -> dict[str, Any]:
    """Kappa del motor determinista por eje, ya medido por el Gate 2 (no se recalcula)."""
    if not path.exists():
        return {}
    datos = json.loads(path.read_text(encoding="utf-8"))
    return {eje.split("_")[-1]: r.get("kappa") for eje, r in (datos.get("ejes") or {}).items()
            if eje.startswith("stance_")}


def evaluar(transporte: Callable[[dict], dict], filas: list[dict], humano: dict[str, dict],
            model: str, baseline: dict[str, Any]) -> dict[str, Any]:
    """Orquesta la medición. `transporte` recibe una petición y devuelve la respuesta cruda
    de Kev; en producción es HTTP, en las pruebas es una función falsa."""
    etiqueta_humana = {"A": "A_postura", "B": "B_certeza", "C": "C_funcion"}
    casos: list[dict] = []
    registros: dict[str, list[dict]] = {"A": [], "B": [], "C": []}
    pares: dict[str, list[tuple[str, str]]] = {"A": [], "B": [], "C": []}
    ids: dict[str, list[str]] = {"A": [], "B": [], "C": []}
    ambiguos = {"A": 0, "B": 0, "C": 0}
    errores_transporte: list[dict] = []

    for fila in filas:
        cid = (fila.get("control_id") or "").strip()
        hum = humano.get(cid, {})
        try:
            crudo = transporte(construir_peticion(fila, model))
            kev = parse_respuesta(crudo)
        except Exception as e:  # red, 422, JSON inválido: se declara, no se rellena
            errores_transporte.append({"control_id": cid, "error": f"{type(e).__name__}: {e}"})
            kev = {}

        caso = {"control_id": cid, "idioma": fila.get("idioma", ""), "kev": {}, "humano": {}}
        for eje, col in etiqueta_humana.items():
            h = (hum.get(col) or "").strip().upper()
            if not h:
                continue
            if h == "AMBIGUO":
                ambiguos[eje] += 1
                continue
            caso["humano"][eje] = h
            k = kev.get(eje)
            if not k:
                continue
            caso["kev"][eje] = k
            correcto = k["etiqueta"] == canon(h)
            pares[eje].append((k["etiqueta"], canon(h)))
            ids[eje].append(cid)
            registros[eje].append({"correcto": correcto, "confianza": k["confianza"]})
        casos.append(caso)

    ejes: dict[str, Any] = {}
    for eje in ("A", "B", "C"):
        r = kappa_cohen(pares[eje])
        r["eje"] = eje
        r["baseline_motor_kappa"] = baseline.get(eje)
        if r["kappa"] is not None and baseline.get(eje) is not None:
            r["delta_vs_motor"] = round(r["kappa"] - baseline[eje], 4)
        r["humano_ambiguo"] = ambiguos[eje]
        r["umbral"] = metricas_por_umbral(registros[eje])
        r["desacuerdos"] = [
            {"id": i, "kev": a, "humano": b}
            for i, (a, b) in zip(ids[eje], pares[eje]) if a != b
        ][:25]
        ejes[eje] = r

    return {
        "generado": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "n_casos": len(casos),
        "ejes": ejes,
        "errores_transporte": errores_transporte,
        "casos": casos,
    }


# ---------------------------------------------------------------- transporte HTTP real

def transporte_http(base_url: str, api_key: str = "", timeout: float = 120.0) -> Callable[[dict], dict]:
    url = base_url.rstrip("/") + "/v1/systemone"

    def _enviar(payload: dict) -> dict:
        cuerpo = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=cuerpo, method="POST",
                                     headers={"Content-Type": "application/json"})
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    return _enviar


def _imprimir_informe(resumen: dict, etiqueta_modelo: str) -> None:
    print("=" * 78)
    print(f"MEDICIÓN KEV — T3 (zero-shot)   modelo={etiqueta_modelo}   n={resumen['n_casos']}")
    print("=" * 78)
    nombres = {"A": "postura", "B": "certeza", "C": "función"}
    for eje in ("A", "B", "C"):
        r = resumen["ejes"][eje]
        base = r.get("baseline_motor_kappa")
        delta = r.get("delta_vs_motor")
        print(f"\nEJE {eje} ({nombres[eje]})   n={r['n']}"
              + (f"   ambiguos_humano={r['humano_ambiguo']}" if r.get("humano_ambiguo") else ""))
        if r["kappa"] is None:
            print("  kappa: sin datos")
            continue
        signo = f"{delta:+.4f}" if delta is not None else "n/d"
        print(f"  kappa Kev vs humano : {r['kappa']}   (motor determinista: {base} · delta {signo})")
        print("  automatizable por umbral de confianza:")
        for t, m in r["umbral"].items():
            ex = m["exactitud"]
            ex_txt = f"{ex:.3f}" if ex is not None else "  n/d"
            marca = "OK" if m["cumple_presupuesto_5pct"] else "no"
            print(f"    >= {t}: cubre {m['n_cubiertas']:2d} ({m['cobertura']*100:4.1f} %)"
                  f"  exactitud {ex_txt}  errores {m['errores']:2d}  [{marca}]")
    if resumen["errores_transporte"]:
        print(f"\nFallos de transporte/servidor: {len(resumen['errores_transporte'])}")
        for e in resumen["errores_transporte"][:5]:
            print(f"  {e['control_id']}: {e['error']}")
    print("=" * 78)


def main() -> None:
    ap = argparse.ArgumentParser(description="Mide Kev sobre la muestra de control T3.")
    ap.add_argument("--base-url", default=os.environ.get("KEV_BASE_URL", "http://127.0.0.1:8009"))
    ap.add_argument("--model", default=os.environ.get("KEV_MODEL", "kev-latest"))
    ap.add_argument("--out", default=str(D / "kev_eval_resultado.json"))
    ap.add_argument("--limit", type=int, default=0, help="mide solo los primeros N casos")
    ap.add_argument("--dry-run", action="store_true", help="imprime la petición del primer caso y sale")
    args = ap.parse_args()

    filas = leer_tsv(D / "control_36.tsv")
    humano = leer_pases()
    if not humano:
        print("No hay etiquetas humanas en data/dataset_v4/pase*_*.csv. Nada que medir.")
        raise SystemExit(1)

    filas = [f for f in filas if (f.get("control_id") or "").strip() in humano]
    if args.limit:
        filas = filas[: args.limit]

    if args.dry_run:
        print(json.dumps(construir_peticion(filas[0], args.model), ensure_ascii=False, indent=2))
        return

    transporte = transporte_http(args.base_url, api_key=os.environ.get("KEV_API_KEY", ""))
    resumen = evaluar(transporte, filas, humano, args.model, _baseline_motor(D / "gate2_resultado.json"))
    resumen["base_url"] = args.base_url

    Path(args.out).write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    _imprimir_informe(resumen, args.model)
    print(f"Informe: {args.out}")


if __name__ == "__main__":
    main()
