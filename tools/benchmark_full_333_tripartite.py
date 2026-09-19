"""Benchmark Tripartito Exhaustivo sobre los 333 Artículos del Corpus de RSU:
1. `thinkuy` (Qwen 2.5 1.5B CoT Epistémico V2 con LoRA) [Ya calculado, reutilizado]
2. `ministral_3b` (Mistral AI 3B vía LM Studio local :1234)
3. `qwen_base` (Qwen 2.5 1.5B Base Zero-Shot sin LoRA)

Genera:
- data/clasificacion_333_tripartita.json (Matriz comparativa completa lado a lado)
- Actualización de estadísticas comparativas para el visualizador
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import httpx
import torch
from unsloth import FastLanguageModel

# Rutas y Endpoints
INPUT_CORPUS_JSON = "data/clasificacion_corpus_unificado_wos_scopus.json"
OUTPUT_TRIPARTITE_JSON = Path("data/clasificacion_333_tripartita.json")
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MISTRAL_MODEL = "mistralai/ministral-3-3b"
BASE_MODEL_NAME = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"

INSTRUCTION_CLASSIFIER = (
    "Eres el metodólogo experto de Thinkuy. Clasifica el artículo científico sobre Responsabilidad Social "
    "Universitaria (RSU) a partir de su título y resumen. Tu labor es asignar su perspectiva temática según "
    "la taxonomía de Duque & Cervantes (2019) y su rol epistemológico:\n\n"
    "PERSPECTIVAS TEMÁTICAS:\n"
    "- P1_MEDICION_ESCALAS: Enfoque psicométrico, escalas cuantitativas, instrumentos, métricas, encuestas de percepción.\n"
    "- P2_ESTRATEGICO_STAKEHOLDERS: Gestión institucional, gobernanza universitaria, teoría de stakeholders, competitividad, modelos organizacionales.\n"
    "- P3_CONEXION_SOCIAL_EXTENSION: Impacto social, compromiso comunitario, extensión, ética civil, formación ciudadana, justicia social.\n\n"
    "ROLES EPISTEMOLÓGICOS: seminal | empirical | methodological | review_synthesis\n\n"
    "REGLA OBLIGATORIA: Responde ÚNICAMENTE un JSON con:\n"
    "{\"rationale\": \"diagnóstico retórico de 10-20 palabras\", "
    "\"perspectiva\": \"P1_MEDICION_ESCALAS|P2_ESTRATEGICO_STAKEHOLDERS|P3_CONEXION_SOCIAL_EXTENSION\", "
    "\"rol\": \"seminal|empirical|methodological|review_synthesis\", "
    "\"claim_central\": \"hallazgo o tesis principal resumida en máx 25 palabras\", "
    "\"confidence\": \"high|low\"}"
)

ALPACA_TEMPLATE = """A continuación se presenta una instrucción que describe una tarea, junto con una entrada que proporciona más contexto. Escribe una respuesta que complete adecuadamente la solicitud.

### Instrucción:
{}

### Entrada:
{}

### Respuesta:
{}"""


def clean_json_response(raw: str) -> Dict[str, Any]:
    try:
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return json.loads(raw.strip())
    except Exception:
        return {"raw": raw.strip()}


def normalize_perspectiva(raw_p: str) -> str:
    p = str(raw_p).upper()
    if "P1" in p or "MEDICION" in p or "ESCALA" in p:
        return "P1_MEDICION_ESCALAS"
    if "P2" in p or "ESTRATEGICO" in p or "STAKEHOLDER" in p or "GESTION" in p:
        return "P2_ESTRATEGICO_STAKEHOLDERS"
    if "P3" in p or "SOCIAL" in p or "EXTENSION" in p or "COMUNIDAD" in p:
        return "P3_CONEXION_SOCIAL_EXTENSION"
    return "P2_ESTRATEGICO_STAKEHOLDERS"


def normalize_rol(raw_r: str) -> str:
    r = str(raw_r).lower()
    if "seminal" in r:
        return "seminal"
    if "empirical" in r:
        return "empirical"
    if "methodological" in r:
        return "methodological"
    if "review" in r or "synthesis" in r:
        return "review_synthesis"
    return "empirical"


def query_ministral(input_text: str) -> Dict[str, Any]:
    t0 = time.time()
    payload = {
        "model": MISTRAL_MODEL,
        "messages": [
            {"role": "system", "content": INSTRUCTION_CLASSIFIER},
            {"role": "user", "content": input_text}
        ],
        "temperature": 0.05,
        "max_tokens": 160
    }
    try:
        r = httpx.post(LM_STUDIO_URL, json=payload, timeout=25.0)
        dt = round(time.time() - t0, 2)
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"].strip()
            parsed = clean_json_response(content)
            parsed["_latency"] = dt
            parsed["_is_valid_json"] = ("raw" not in parsed)
            return parsed
        else:
            return {"error": f"HTTP {r.status_code}", "_latency": dt, "_is_valid_json": False}
    except Exception as e:
        return {"error": str(e), "_latency": round(time.time() - t0, 2), "_is_valid_json": False}


def main():
    print("=" * 95)
    print("BENCHMARK TRIPARTITO COMPLETO: THINKUY vs MINISTRAL 3B vs QWEN 2.5 BASE")
    print("Corpus Evaluado: 333 Artículos Científicos de RSU (Duque & Cervantes 2019)")
    print("=" * 95)

    # 1. Cargar corpus existente con inferencias de `thinkuy`
    with open(INPUT_CORPUS_JSON, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    # Si ya existe un progreso previo, cargarlo
    if OUTPUT_TRIPARTITE_JSON.exists():
        try:
            with open(OUTPUT_TRIPARTITE_JSON, "r", encoding="utf-8") as f:
                tripartite_data = json.load(f)
                print(f"[REANUDACIÓN] Cargados {len(tripartite_data)} registros con progreso previo.")
        except Exception:
            tripartite_data = corpus
    else:
        tripartite_data = corpus

    print(f"\n[1/3] Verificando Ministral 3B en LM Studio...")
    test_min = query_ministral("Test de conexión.")
    if "error" in test_min:
        print(f"[ERROR CRÍTICO] LM Studio no responde correctamente: {test_min['error']}")
        sys.exit(1)
    print(f"✓ Ministral 3B respondiendo en {test_min.get('_latency')}s.")

    # 2. Inferencia Masiva sobre Ministral 3B
    print("\n" + "=" * 95)
    print(f"[2/3] EJECUTANDO INFERENCIA SOBRE LOS 333 ARTÍCULOS CON MINISTRAL 3B")
    print("=" * 95)

    min_persp_counter = Counter()
    min_latencies = []
    min_valid_json = 0

    for idx, art in enumerate(tripartite_data, 1):
        # Si ya fue procesado en una corrida previa, saltar
        if "ministral" in art:
            p_norm = art["ministral"].get("perspectiva_norm", "P2_ESTRATEGICO_STAKEHOLDERS")
            min_persp_counter[p_norm] += 1
            continue

        input_text = (
            f"Título: {art['title']}\n"
            f"Año: {art['year']} | Revista: {art['journal']}\n"
            f"Autores: {art['authors']}\n"
            f"Resumen: {art.get('abstract', '')[:900]}"
        )

        res = query_ministral(input_text)
        raw_p = res.get("perspectiva", "")
        p_norm = normalize_perspectiva(raw_p)
        r_norm = normalize_rol(res.get("rol", ""))

        min_persp_counter[p_norm] += 1
        lat = res.get("_latency", 0)
        min_latencies.append(lat)
        if res.get("_is_valid_json"):
            min_valid_json += 1

        art["ministral"] = {
            "perspectiva_raw": raw_p,
            "perspectiva_norm": p_norm,
            "rol_norm": r_norm,
            "rationale": res.get("rationale", ""),
            "claim": res.get("claim_central", ""),
            "latency": lat,
            "is_valid_json": res.get("_is_valid_json", False)
        }

        if idx % 15 == 0 or idx == len(tripartite_data):
            avg_lat = round(sum(min_latencies) / len(min_latencies), 2) if min_latencies else 0
            print(f"  [Ministral {idx:3d}/{len(tripartite_data)}] {art['title'][:50]}... -> {p_norm} [{lat}s | prom: {avg_lat}s]")
            # Guardado incremental
            with open(OUTPUT_TRIPARTITE_JSON, "w", encoding="utf-8") as f:
                json.dump(tripartite_data, f, ensure_ascii=False, indent=2)

    print("\n✓ Inferencia con Ministral 3B finalizada.")

    # 3. Cargar Qwen Base en GPU
    print("\n" + "=" * 95)
    print(f"[3/3] CARGANDO QWEN 2.5 1.5B BASE (ZERO-SHOT SIN LoRA) EN GPU")
    print("=" * 95)
    t_load = time.time()
    model_base, tokenizer_base = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL_NAME,
        max_seq_length=1024,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model_base)
    print(f"✓ Qwen Base cargado en {round(time.time() - t_load, 2)}s.")

    qwen_persp_counter = Counter()
    qwen_latencies = []
    qwen_valid_json = 0

    for idx, art in enumerate(tripartite_data, 1):
        if "qwen_base" in art:
            p_norm = art["qwen_base"].get("perspectiva_norm", "P2_ESTRATEGICO_STAKEHOLDERS")
            qwen_persp_counter[p_norm] += 1
            continue

        input_text = (
            f"Título: {art['title']}\n"
            f"Año: {art['year']} | Revista: {art['journal']}\n"
            f"Autores: {art['authors']}\n"
            f"Resumen: {art.get('abstract', '')[:900]}"
        )

        formatted = ALPACA_TEMPLATE.format(INSTRUCTION_CLASSIFIER, input_text, "")
        inputs = tokenizer_base([formatted], return_tensors="pt").to("cuda")

        t_inf = time.time()
        with torch.no_grad():
            outputs = model_base.generate(
                **inputs,
                max_new_tokens=160,
                use_cache=True,
                temperature=0.05,
                pad_token_id=tokenizer_base.eos_token_id
            )
        elapsed = round(time.time() - t_inf, 2)
        qwen_latencies.append(elapsed)

        resp_text = tokenizer_base.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
        parsed = clean_json_response(resp_text)
        is_valid = ("raw" not in parsed)
        if is_valid:
            qwen_valid_json += 1

        raw_p = parsed.get("perspectiva", "")
        p_norm = normalize_perspectiva(raw_p)
        r_norm = normalize_rol(parsed.get("rol", ""))

        qwen_persp_counter[p_norm] += 1

        art["qwen_base"] = {
            "perspectiva_raw": raw_p,
            "perspectiva_norm": p_norm,
            "rol_norm": r_norm,
            "rationale": parsed.get("rationale", ""),
            "claim": parsed.get("claim_central", ""),
            "latency": elapsed,
            "is_valid_json": is_valid
        }

        if idx % 20 == 0 or idx == len(tripartite_data):
            avg_lat = round(sum(qwen_latencies) / len(qwen_latencies), 2) if qwen_latencies else 0
            print(f"  [Qwen Base {idx:3d}/{len(tripartite_data)}] {art['title'][:50]}... -> {p_norm} [{elapsed}s | prom: {avg_lat}s]")
            with open(OUTPUT_TRIPARTITE_JSON, "w", encoding="utf-8") as f:
                json.dump(tripartite_data, f, ensure_ascii=False, indent=2)

    # Guardado final consolidado
    with open(OUTPUT_TRIPARTITE_JSON, "w", encoding="utf-8") as f:
        json.dump(tripartite_data, f, ensure_ascii=False, indent=2)

    # Estadísticas Thinkuy
    thinkuy_persp = Counter(a.get("perspectiva", "P2_ESTRATEGICO_STAKEHOLDERS") for a in tripartite_data)
    total_arts = len(tripartite_data)

    print("\n" + "=" * 95)
    print("BALANCE FINAL COMPARATIVO LADO A LADO (333 ARTÍCULOS)")
    print("=" * 95)
    print(f"{'Perspectiva Temática':<32} | {'Thinkuy (Afinado)':<18} | {'Ministral 3B':<16} | {'Qwen Base (Zero-Shot)'}")
    print("-" * 95)
    for p in ["P1_MEDICION_ESCALAS", "P2_ESTRATEGICO_STAKEHOLDERS", "P3_CONEXION_SOCIAL_EXTENSION"]:
        pct_t = round(thinkuy_persp[p] / total_arts * 100, 1)
        pct_m = round(min_persp_counter[p] / total_arts * 100, 1)
        pct_q = round(qwen_persp_counter[p] / total_arts * 100, 1)
        print(f"{p:<32} | {pct_t:4.1f}% ({thinkuy_persp[p]:3d})     | {pct_m:4.1f}% ({min_persp_counter[p]:3d})   | {pct_q:4.1f}% ({qwen_persp_counter[p]:3d})")

    # Concordancia mutua
    coinciden_thinkuy_ministral = sum(1 for a in tripartite_data if a.get("perspectiva") == a.get("ministral", {}).get("perspectiva_norm"))
    coinciden_thinkuy_qwen = sum(1 for a in tripartite_data if a.get("perspectiva") == a.get("qwen_base", {}).get("perspectiva_norm"))
    coinciden_ministral_qwen = sum(1 for a in tripartite_data if a.get("ministral", {}).get("perspectiva_norm") == a.get("qwen_base", {}).get("perspectiva_norm"))

    print("\n" + "-" * 95)
    print("TASAS DE CONCORDANCIA INTER-MODELO:")
    print(f"  * Thinkuy vs. Ministral 3B : {coinciden_thinkuy_ministral}/{total_arts} ({round(coinciden_thinkuy_ministral/total_arts*100, 1)}%)")
    print(f"  * Thinkuy vs. Qwen Base    : {coinciden_thinkuy_qwen}/{total_arts} ({round(coinciden_thinkuy_qwen/total_arts*100, 1)}%)")
    print(f"  * Ministral vs. Qwen Base  : {coinciden_ministral_qwen}/{total_arts} ({round(coinciden_ministral_qwen/total_arts*100, 1)}%)")
    print("=" * 95)
    print(f"[ÉXITO] Matriz tripartita guardada en: {OUTPUT_TRIPARTITE_JSON}")


if __name__ == "__main__":
    main()
