"""Benchmark Tripartito Riguroso en Vivo:
1. Qwen 2.5 1.5B Base (Zero-shot)
2. Qwen 2.5 1.5B CoT V2 (Nuestro Modelo Afinado con LoRA r=32 + Negativos Difíciles)
3. Ministral 3B (Mistral AI vía LM Studio API local)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
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
BASE_MODEL_NAME = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"
OUR_LORA_PATH = "models/qwen_epistemic_v2_cot"
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MISTRAL_MODEL = "mistralai/ministral-3-3b"

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

TEST_CASES = [
    {
        "id": 1,
        "categoria": "FALSO CONSENSO EN ANTECEDENTES (VERBO AFIRMATIVO)",
        "input": 'Sección: Marco Teórico\nContexto de citación: "Tal como se consigna en la revisión monográfica de Albornoz et al. (2021), la varianza factorial en pruebas psicométricas constituye un eje articulador central del debate contemporáneo."',
        "gold_stance": "neutral_or_mention",
        "gold_claim": "",
        "dificultad": "Trampa de dicción: parece consenso por 'constituye un eje', pero es una cita expositiva de antecedentes."
    },
    {
        "id": 2,
        "categoria": "DISENSO CON CONCESIÓN E IRONÍA / SESGO PALMARIO",
        "input": 'Sección: Discusión\nContexto de citación: "Si bien Silva (2019) postula la invulnerabilidad del protocolo ante ataques de canal lateral, nuestra experimentación longitudinal constata un sesgo palmario en sus métricas, refutando frontalmente sus conclusiones de estabilidad."',
        "gold_stance": "contrasting_or_refuting",
        "gold_claim": "nuestra experimentación longitudinal constata un sesgo palmario en sus métricas, refutando frontalmente sus conclusiones de estabilidad",
        "dificultad": "Concesión inicial ('Si bien...') seguida de refutación directa con léxico culto ('sesgo palmario')."
    },
    {
        "id": 3,
        "categoria": "CONSENSO GENUINO Y CORROBORACIÓN EMPÍRICA",
        "input": 'Sección: Resultados y Discusión\nContexto de citación: "En plena concordancia con lo demostrado por Mendoza y Ruiz (2022), los datos empíricos de nuestra muestra corroboran categóricamente una reducción del error basal del 42%."',
        "gold_stance": "supporting_or_agreement",
        "gold_claim": "los datos empíricos de nuestra muestra corroboran categóricamente una reducción del error basal del 42%",
        "dificultad": "Acuerdo empírico explícito con datos propios que ratifican la tesis citada."
    },
    {
        "id": 4,
        "categoria": "ADOPCIÓN METODOLÓGICA CON PROTOCOLO CIENTÍFICO",
        "input": 'Sección: Metodología\nContexto de citación: "Para la calibración psicométrica de la escala se adoptó íntegramente la adaptación transcultural y la matriz factorial validada por Hernández-Sampieri et al. (2018)."',
        "gold_stance": "methodological_adoption",
        "gold_claim": "se adoptó íntegramente la adaptación transcultural y la matriz factorial validada por Hernández-Sampieri et al. (2018)",
        "dificultad": "Uso instrumental de escala, matriz y diseño psicométrico ajeno."
    },
    {
        "id": 5,
        "categoria": "DISENSO CLÍNICO EN INGLÉS (PRUEBA MULTILINGÜE Y FIDELIDAD VERBATIM)",
        "input": 'Sección: Discussion\nContexto de citación: "In sharp contrast to the conclusions reached by Smith and Jones (2020), our randomized clinical trial failed to detect any statistically significant difference between the treated group and the placebo cohort."',
        "gold_stance": "contrasting_or_refuting",
        "gold_claim": "our randomized clinical trial failed to detect any statistically significant difference between the treated group and the placebo cohort",
        "dificultad": "Cita en inglés: verificar si el modelo traduce o preserva la subcadena idéntica sin alterar."
    }
]


def clean_json_response(raw: str) -> Dict[str, Any]:
    try:
        # Extraer primer bloque json
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return json.loads(raw.strip())
    except Exception:
        return {"raw": raw.strip()}


def query_mistral_api(prompt_input: str) -> Dict[str, Any]:
    t0 = time.time()
    payload = {
        "model": MISTRAL_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_COT},
            {"role": "user", "content": prompt_input}
        ],
        "temperature": 0.05,
        "max_tokens": 200
    }
    try:
        r = httpx.post(LM_STUDIO_URL, json=payload, timeout=25.0)
        dt = time.time() - t0
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"].strip()
            parsed = clean_json_response(content)
            parsed["_latency"] = round(dt, 2)
            parsed["_raw_len"] = len(content)
            return parsed
        else:
            return {"error": f"HTTP {r.status_code}: {r.text}", "_latency": round(dt, 2)}
    except Exception as e:
        return {"error": str(e), "_latency": round(time.time() - t0, 2)}


def run_qwen_inference(model, tokenizer, prompt_input: str) -> Dict[str, Any]:
    t0 = time.time()
    formatted = ALPACA_TEMPLATE.format(SYSTEM_PROMPT_COT, prompt_input)
    inputs = tokenizer([formatted], return_tensors="pt").to("cuda")
    
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=180,
            use_cache=True,
            temperature=0.05,
            pad_token_id=tokenizer.eos_token_id
        )
    
    dt = time.time() - t0
    # Decodificar solo la respuesta nueva
    resp_text = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
    parsed = clean_json_response(resp_text)
    parsed["_latency"] = round(dt, 2)
    parsed["_raw_len"] = len(resp_text)
    return parsed


def main():
    print("=" * 90)
    print("BENCHMARK TRIPARTITO RIGUROSO: QWEN BASE vs QWEN V2 CoT (AFINADO) vs MINISTRAL 3B")
    print("=" * 90)

    # 1. Cargar Qwen V2 Afinado (Nuestro Modelo)
    print("\n[1/3] Cargando Qwen 2.5 1.5B CoT V2 (con adaptadores LoRA r=32)...")
    model_v2, tokenizer_v2 = FastLanguageModel.from_pretrained(
        model_name=OUR_LORA_PATH,
        max_seq_length=1024,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model_v2)
    print("✓ Qwen V2 CoT listo en GPU.")

    # 2. Cargar Qwen Base (Zero-Shot)
    print("\n[2/3] Cargando Qwen 2.5 1.5B Base (Zero-Shot sin LoRA)...")
    model_base, tokenizer_base = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL_NAME,
        max_seq_length=1024,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model_base)
    print("✓ Qwen Base listo en GPU.")

    # 3. Comprobar Ministral 3B
    print(f"\n[3/3] Verificando conexión con Ministral 3B en LM Studio (:1234)...")
    test_m = query_mistral_api("Test de conectividad.")
    if "error" in test_m:
        print(f"⚠️ Aviso al conectar con Ministral: {test_m['error']}")
    else:
        print(f"✓ Ministral 3B respondiendo en LM Studio ({test_m.get('_latency', 0)}s).")

    print("\n" + "=" * 90)
    print("EJECUTANDO EVALUACIÓN COMPARATIVA LADO A LADO")
    print("=" * 90)

    results = []

    for tc in TEST_CASES:
        print(f"\n" + "-" * 90)
        print(f"CASO {tc['id']}: {tc['categoria']}")
        print(f"Entrada: {tc['input']}")
        print(f"Postura Esperada: {tc['gold_stance']} | Desafío: {tc['dificultad']}")
        print("-" * 90)

        # Inferencia 1: Qwen Base
        res_base = run_qwen_inference(model_base, tokenizer_base, tc["input"])
        print(f"🤖 [1. Qwen Base 1.5B]:")
        print(f"   • Stance: {res_base.get('stance', 'N/A')}")
        print(f"   • Rationale: {res_base.get('rationale', 'N/A')}")
        print(f"   • Claim: '{res_base.get('claim', '')}'")
        print(f"   • Confianza: {res_base.get('confidence', 'N/A')} | Latencia: {res_base.get('_latency')}s")

        # Inferencia 2: Nuestro Modelo V2
        res_v2 = run_qwen_inference(model_v2, tokenizer_v2, tc["input"])
        print(f"🧠 [2. NUESTRO Qwen V2 CoT 1.5B]:")
        print(f"   • Stance: {res_v2.get('stance', 'N/A')}")
        print(f"   • Rationale: {res_v2.get('rationale', 'N/A')}")
        print(f"   • Claim: '{res_v2.get('claim', '')}'")
        print(f"   • Confianza: {res_v2.get('confidence', 'N/A')} | Latencia: {res_v2.get('_latency')}s")

        # Inferencia 3: Ministral 3B
        res_mistral = query_mistral_api(tc["input"])
        print(f"⚡ [3. Ministral 3B (Mistral AI)]:")
        print(f"   • Stance: {res_mistral.get('stance', 'N/A')}")
        print(f"   • Rationale: {res_mistral.get('rationale', 'N/A')}")
        print(f"   • Claim: '{res_mistral.get('claim', '')}'")
        print(f"   • Confianza: {res_mistral.get('confidence', 'N/A')} | Latencia: {res_mistral.get('_latency')}s")

        results.append({
            "case": tc,
            "qwen_base": res_base,
            "qwen_v2_cot": res_v2,
            "ministral_3b": res_mistral
        })

    # Guardar reporte JSON
    out_file = Path("data/auditorias_y_benchmarks/benchmark_tripartito_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Resultados completos guardados en: {out_file}")


if __name__ == "__main__":
    main()
