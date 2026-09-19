"""Evaluación Robusta Tripartita sobre Conjunto Ciego Holdout (N=32 citas estratificadas):
1. Qwen 2.5 1.5B Base (Zero-Shot)
2. NUESTRO Qwen 2.5 1.5B CoT V2 (Afinado con LoRA r=32 + Negativos Difíciles)
3. Ministral 3B (Mistral AI vía LM Studio API local)

Calcula:
- Accuracy Global y por Postura (Consenso, Disenso, Metodología, Neutro)
- Tasa de Fidelidad Verbatim (Subcadena literal exacta sin alucinación)
- Formato JSON Válido (%)
- Latencia promedio de inferencia (s)
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from collections import defaultdict
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

TEST_DATASET_PATH = "data/epistemic_test_cot.jsonl"
OUR_LORA_PATH = "models/qwen_epistemic_v2_cot"
BASE_MODEL_NAME = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MISTRAL_MODEL = "mistralai/ministral-3-3b"
OUT_RESULTS_FILE = Path("data/auditorias_y_benchmarks/robust_benchmark_results.json")

SYSTEM_PROMPT_COT = (
    "Eres un asistente de análisis epistemológico y retórico de literatura científica especializada en español. "
    "Tu labor es evaluar el párrafo donde un artículo cita a otra obra y clasificar su función retórica "
    "en una de estas 4 categorías exactas:\n"
    "- supporting_or_agreement: posible consenso (el autor apoya, confirma, replica o halla evidencia a favor).\n"
    "- contrasting_or_refuting: posible disenso (el autor cuestiona, contradice, refuta, señala inconsistencias o límites).\n"
    "- methodological_adoption: posible adopción metodológica (se adopta o adapta método, escala, software, diseño o protocolo).\n"
    "- neutral_or_mention: posible mención contextual (mención de estado del arte o literatura previa sin postura activa).\n\n"
    "REGLA OBLIGATORIA: Primero emite un 'rationale' (breve diagnóstico retórico de 10 a 20 palabras que analice "
    "conectores, léxico culto y función argumental). Luego declara 'stance', extrae el 'claim' literal exacto del texto "
    "(subcadena idéntica sin alterar, máximo 25 palabras; o cadena vacía si es neutral) y 'confidence'.\n"
    "Responde ÚNICAMENTE un JSON con: {\"rationale\": \"...\", \"stance\": \"...\", \"claim\": \"...\", \"confidence\": \"high|low\"}."
)

ALPACA_TEMPLATE = """A continuación se presenta una instrucción que describe una tarea, junto con una entrada que proporciona más contexto. Escribe una respuesta que complete adecuadamente la solicitud.

### Instrucción:
{}

### Entrada:
{}

### Respuesta:
"""


def load_stratified_test_sample(samples_per_class: int = 8) -> List[Dict[str, Any]]:
    """Carga una muestra estratificada y balanceada de citas ciegas holdout."""
    by_class = defaultdict(list)
    with open(TEST_DATASET_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                out = json.loads(obj["output"])
                stance = out["stance"]
                by_class[stance].append({
                    "input": obj["input"],
                    "gold_stance": stance,
                    "gold_claim": out.get("claim", ""),
                    "gold_rationale": out.get("rationale", "")
                })
            except Exception:
                continue

    random.seed(42)
    sample = []
    classes = ["supporting_or_agreement", "contrasting_or_refuting", "methodological_adoption", "neutral_or_mention"]
    for c in classes:
        pool = by_class[c]
        random.shuffle(pool)
        sample.extend(pool[:samples_per_class])

    random.shuffle(sample)
    for idx, s in enumerate(sample, 1):
        s["id"] = idx
    return sample


def clean_json_response(raw: str) -> Dict[str, Any]:
    try:
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return json.loads(raw.strip())
    except Exception:
        return {"raw": raw.strip(), "stance": "parse_error", "claim": "", "rationale": ""}


def query_mistral_api(prompt_input: str) -> Dict[str, Any]:
    t0 = time.time()
    payload = {
        "model": MISTRAL_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_COT},
            {"role": "user", "content": prompt_input}
        ],
        "temperature": 0.05,
        "max_tokens": 180
    }
    try:
        r = httpx.post(LM_STUDIO_URL, json=payload, timeout=25.0)
        dt = time.time() - t0
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"].strip()
            parsed = clean_json_response(content)
            parsed["_latency"] = round(dt, 2)
            parsed["_valid_json"] = ("parse_error" not in parsed.get("stance", ""))
            return parsed
        else:
            return {"stance": "error", "claim": "", "rationale": f"HTTP {r.status_code}", "_latency": round(dt, 2), "_valid_json": False}
    except Exception as e:
        return {"stance": "error", "claim": "", "rationale": str(e), "_latency": round(time.time() - t0, 2), "_valid_json": False}


def run_qwen_inference(model, tokenizer, prompt_input: str) -> Dict[str, Any]:
    t0 = time.time()
    formatted = ALPACA_TEMPLATE.format(SYSTEM_PROMPT_COT, prompt_input)
    inputs = tokenizer([formatted], return_tensors="pt").to("cuda")
    
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=150,
            use_cache=True,
            temperature=0.05,
            pad_token_id=tokenizer.eos_token_id
        )
    
    dt = time.time() - t0
    resp_text = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
    parsed = clean_json_response(resp_text)
    parsed["_latency"] = round(dt, 2)
    parsed["_valid_json"] = ("parse_error" not in parsed.get("stance", ""))
    return parsed


def check_verbatim_fidelity(extracted_claim: str, input_text: str, gold_stance: str) -> bool:
    """Verifica si el claim extraído cumple la regla de fidelidad literal sin alucinaciones."""
    if not extracted_claim or extracted_claim.strip() == "":
        return gold_stance == "neutral_or_mention"
    
    # Extraer el texto de la cita quitando comillas de escape
    claim_clean = extracted_claim.strip().strip('"').strip("'").lower()
    input_clean = input_text.lower()
    
    # Subcadena exacta o casi idéntica (omitiendo espacios múltiples)
    claim_words = claim_clean.split()
    if len(claim_words) == 0:
        return True
    
    reconstructed = " ".join(claim_words)
    return reconstructed in " ".join(input_clean.split())


def compute_aggregate_metrics(results: List[Dict[str, Any]], model_key: str) -> Dict[str, Any]:
    total = len(results)
    correct_stance = 0
    verbatim_count = 0
    valid_json_count = 0
    total_latency = 0.0
    
    class_totals = defaultdict(int)
    class_correct = defaultdict(int)

    for item in results:
        gold = item["gold_stance"]
        pred_obj = item[model_key]
        pred_stance = pred_obj.get("stance", "")
        pred_claim = pred_obj.get("claim", "")
        
        class_totals[gold] += 1
        if pred_stance == gold:
            correct_stance += 1
            class_correct[gold] += 1
            
        if pred_obj.get("_valid_json", False):
            valid_json_count += 1
            
        if check_verbatim_fidelity(pred_claim, item["input"], gold):
            verbatim_count += 1
            
        total_latency += pred_obj.get("_latency", 0.0)

    per_class_acc = {}
    for c in ["supporting_or_agreement", "contrasting_or_refuting", "methodological_adoption", "neutral_or_mention"]:
        tot = class_totals[c]
        per_class_acc[c] = round((class_correct[c] / tot) * 100, 1) if tot > 0 else 0.0

    return {
        "accuracy_global": round((correct_stance / total) * 100, 1),
        "verbatim_fidelity": round((verbatim_count / total) * 100, 1),
        "valid_json_rate": round((valid_json_count / total) * 100, 1),
        "avg_latency": round(total_latency / total, 2),
        "per_class_accuracy": per_class_acc,
        "correct_samples": f"{correct_stance}/{total}"
    }


def main():
    print("=" * 90)
    print("EVALUACIÓN ROBUSTA TRIPARTITA: QWEN BASE vs QWEN V2 CoT vs MINISTRAL 3B")
    print("Conjunto Ciego Holdout Estratificado: N=32 citas (8 por postura)")
    print("=" * 90)

    # 1. Cargar muestra
    samples = load_stratified_test_sample(samples_per_class=8)
    print(f"\n✓ Muestra holdout estratificada cargada: {len(samples)} citas independientes.")

    # 2. Cargar Qwen V2 CoT
    print("\n[1/3] Cargando Qwen 2.5 1.5B CoT V2 (LoRA r=32)...")
    model_v2, tokenizer_v2 = FastLanguageModel.from_pretrained(
        model_name=OUR_LORA_PATH,
        max_seq_length=1024,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model_v2)
    print("✓ Qwen V2 CoT listo.")

    # 3. Cargar Qwen Base
    print("\n[2/3] Cargando Qwen 2.5 1.5B Base (Zero-Shot)...")
    model_base, tokenizer_base = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL_NAME,
        max_seq_length=1024,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model_base)
    print("✓ Qwen Base listo.")

    # 4. Probar Ministral
    print("\n[3/3] Verificando Ministral 3B en LM Studio (:1234)...")
    test_m = query_mistral_api("Test ping")
    if "error" in test_m.get("stance", ""):
        print(f"⚠️ Advertencia con Ministral: {test_m}")
    else:
        print("✓ Ministral 3B listo.")

    print("\n" + "=" * 90)
    print("INICIANDO INFERENCIA COMPARATIVA (32 citas x 3 modelos = 96 inferencias)")
    print("=" * 90)

    detailed_results = []

    for i, s in enumerate(samples, 1):
        print(f"Procesando muestra [{i:02d}/32] (Gold: {s['gold_stance']})...", end="\r")

        # Modelo 1: Base
        res_base = run_qwen_inference(model_base, tokenizer_base, s["input"])
        # Modelo 2: V2 CoT
        res_v2 = run_qwen_inference(model_v2, tokenizer_v2, s["input"])
        # Modelo 3: Ministral
        res_mistral = query_mistral_api(s["input"])

        item_res = {
            "id": s["id"],
            "input": s["input"],
            "gold_stance": s["gold_stance"],
            "gold_claim": s["gold_claim"],
            "qwen_base": res_base,
            "qwen_v2_cot": res_v2,
            "ministral_3b": res_mistral,
            "is_correct_base": res_base.get("stance") == s["gold_stance"],
            "is_correct_v2": res_v2.get("stance") == s["gold_stance"],
            "is_correct_mistral": res_mistral.get("stance") == s["gold_stance"],
        }
        detailed_results.append(item_res)

    print("\n✓ Inferencia de las 32 muestras completada con éxito.")

    # Métricas agregadas
    metrics_base = compute_aggregate_metrics(detailed_results, "qwen_base")
    metrics_v2 = compute_aggregate_metrics(detailed_results, "qwen_v2_cot")
    metrics_mistral = compute_aggregate_metrics(detailed_results, "ministral_3b")

    summary = {
        "sample_size": len(samples),
        "timestamp": time.time(),
        "models": {
            "qwen_base": metrics_base,
            "qwen_v2_cot": metrics_v2,
            "ministral_3b": metrics_mistral,
        },
        "details": detailed_results
    }

    # Guardar en disco
    OUT_RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 90)
    print("CUADRO FINAL DE RESULTADOS (N=32 CITAS CIEGAS)")
    print("=" * 90)
    print(f"{'Métrica':<35} | {'Qwen Base':<15} | {'Ministral 3B':<15} | {'NUESTRO Qwen V2':<15}")
    print("-" * 90)
    print(f"{'Accuracy Global':<35} | {metrics_base['accuracy_global']}% ({metrics_base['correct_samples']}) | {metrics_mistral['accuracy_global']}% ({metrics_mistral['correct_samples']}) | {metrics_v2['accuracy_global']}% ({metrics_v2['correct_samples']})")
    print(f"{'Fidelidad Verbatim (Sin Alucinación)':<35} | {metrics_base['verbatim_fidelity']}% | {metrics_mistral['verbatim_fidelity']}% | {metrics_v2['verbatim_fidelity']}%")
    print(f"{'Formato JSON Válido':<35} | {metrics_base['valid_json_rate']}% | {metrics_mistral['valid_json_rate']}% | {metrics_v2['valid_json_rate']}%")
    print(f"{'Latencia Promedio por Cita':<35} | {metrics_base['avg_latency']}s | {metrics_mistral['avg_latency']}s | {metrics_v2['avg_latency']}s")
    print("-" * 90)
    print("ACCURACY POR CLASE ESPECÍFICA:")
    for c, label in [
        ("neutral_or_mention", "Menciones Neutrales"),
        ("supporting_or_agreement", "Consensos Reales"),
        ("contrasting_or_refuting", "Disensos / Refutaciones"),
        ("methodological_adoption", "Adopción Metodológica")
    ]:
        print(f"  • {label:<33} | {metrics_base['per_class_accuracy'][c]}% | {metrics_mistral['per_class_accuracy'][c]}% | {metrics_v2['per_class_accuracy'][c]}%")
    print("=" * 90)
    print(f"Reporte completo guardado en: {OUT_RESULTS_FILE}")


if __name__ == "__main__":
    main()
