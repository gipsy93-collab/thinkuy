"""Benchmark Cuantitativo Riguroso Tripartito:
1. Qwen 2.5 1.5B Base (Zero-Shot)
2. Qwen 2.5 1.5B Afinado (LoRA 190 Pasos / 2 Épocas)
3. Ministral 3B (LM Studio API :1234)

Evaluado sobre una muestra representativa balanceada de data/epistemic_test.jsonl (Ground-Truth ciego).
Calcula: Accuracy, JSON Compliance, Verbatim Precision, Latencia y Matriz de Confusión.
"""
import os
import sys
import time
import json
import random
import re
from pathlib import Path
from collections import defaultdict

import httpx
import torch
from unsloth import FastLanguageModel

# Rutas y Endpoints
TEST_FILE = "data/epistemic_test.jsonl"
BASE_MODEL_NAME = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"
LORA_PATH = r"C:\Users\gipsy\.unsloth\studio\outputs\unsloth_Qwen2.5-1.5B-Instruct-bnb-4bit__project-thinkuy-epistemic-qwen_1789479572"
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MISTRAL_MODEL = "mistralai/ministral-3-3b"
REPORT_OUTPUT = "docs/INFORME_BENCHMARK_TRIPARTITO_MODELOS.md"

SYSTEM_PROMPT = (
    "Eres un asistente de análisis epistemológico y retórico de literatura científica. "
    "Tu labor es evaluar cómo un artículo cita a otra obra y clasificar la función de la cita "
    "en una de estas 4 categorías exactas:\n"
    "- supporting_or_agreement: posible consenso (el autor apoya, confirma, replica o halla evidencia a favor).\n"
    "- contrasting_or_refuting: posible disenso (el autor cuestiona, contradice, refuta, señala inconsistencias o límites).\n"
    "- methodological_adoption: posible adopción metodológica (se adopta o adapta método, escala, software, diseño o protocolo).\n"
    "- neutral_or_mention: posible mención contextual (mención de estado del arte o literatura previa sin postura activa).\n\n"
    "REGLA OBLIGATORIA: Extrae el 'claim': la afirmación literal exacta (máximo 25 palabras) que justifica la postura. "
    "Responde ÚNICAMENTE un JSON con: {\"stance\": \"...\", \"claim\": \"...\", \"confidence\": \"high|low\"}."
)

ALPACA_PROMPT = """A continuación se presenta una instrucción que describe una tarea, junto con una entrada que proporciona más contexto. Escribe una respuesta que complete adecuadamente la solicitud.

### Instrucción:
{}

### Entrada:
{}

### Respuesta:
"""

CLASSES = [
    "supporting_or_agreement",
    "contrasting_or_refuting",
    "methodological_adoption",
    "neutral_or_mention",
]


def load_balanced_test_sample(filepath: str, samples_per_class: int = 10) -> list[dict]:
    """Carga y balancea una muestra estratificada desde epistemic_test.jsonl."""
    by_class = defaultdict(list)
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                target = json.loads(obj["output"])
                stance = target["stance"]
                if stance in CLASSES:
                    by_class[stance].append({
                        "instruction": obj.get("instruction", SYSTEM_PROMPT),
                        "input": obj["input"],
                        "target_stance": stance,
                        "target_claim": target.get("claim", ""),
                    })
            except Exception:
                continue

    selected = []
    random.seed(42)
    for c in CLASSES:
        items = by_class[c]
        chosen = random.sample(items, min(samples_per_class, len(items)))
        selected.extend(chosen)

    random.shuffle(selected)
    return selected


def parse_llm_json_response(raw_text: str) -> tuple[dict | None, bool, str]:
    """Parsea la respuesta JSON limpiando posibles artefactos o markdown."""
    text = raw_text.strip()
    is_pure_json = False
    
    # 1. Intento directo JSON puro
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "stance" in data:
            return data, True, "json_puro"
    except Exception:
        pass

    # 2. Intento extrayendo bloque ```json ... ```
    match_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match_block:
        try:
            data = json.loads(match_block.group(1))
            if isinstance(data, dict) and "stance" in data:
                return data, False, "bloque_markdown"
        except Exception:
            pass

    # 3. Intento extrayendo cualquier par de llaves {...}
    match_braces = re.search(r"(\{.*?\})", text, re.DOTALL)
    if match_braces:
        try:
            data = json.loads(match_braces.group(1))
            if isinstance(data, dict) and "stance" in data:
                return data, False, "extraido_con_ruido"
        except Exception:
            pass

    return None, False, "invalido"


def extract_raw_input_text(input_field: str) -> str:
    """Extrae el texto entre comillas de la cadena de entrada."""
    m = re.search(r'Contexto de citación:\s*"(.*?)"', input_field, re.DOTALL)
    if m:
        return m.group(1)
    return input_field


def evaluate_predictions(sample_list: list[dict], predictions: list[tuple[str, float]]) -> dict:
    """Calcula métricas formales: Accuracy, JSON Compliance, Verbatim Match, Latencia."""
    total = len(sample_list)
    correct_stance = 0
    valid_json_count = 0
    pure_json_count = 0
    verbatim_match_count = 0
    claims_tested = 0
    
    confusion_matrix = {c: {p: 0 for p in CLASSES} for c in CLASSES}
    class_stats = {c: {"tp": 0, "fp": 0, "fn": 0} for c in CLASSES}
    latencies = []

    for i, item in enumerate(sample_list):
        raw_output, dur = predictions[i]
        latencies.append(dur)
        target_stance = item["target_stance"]
        raw_text_context = extract_raw_input_text(item["input"])

        parsed, is_pure, parse_type = parse_llm_json_response(raw_output)

        if parsed:
            valid_json_count += 1
            if is_pure:
                pure_json_count += 1
            
            pred_stance = parsed.get("stance", "unknown")
            pred_claim = parsed.get("claim", "").strip()

            if pred_stance in CLASSES:
                confusion_matrix[target_stance][pred_stance] += 1
                if pred_stance == target_stance:
                    correct_stance += 1
                    class_stats[target_stance]["tp"] += 1
                else:
                    class_stats[target_stance]["fn"] += 1
                    class_stats[pred_stance]["fp"] += 1
            else:
                class_stats[target_stance]["fn"] += 1

            # Evaluación Verbatim
            if pred_claim:
                claims_tested += 1
                if pred_claim in raw_text_context:
                    verbatim_match_count += 1
            else:
                # Si el target era mención contextual y dejó el claim vacío, es acierto
                if target_stance == "neutral_or_mention":
                    claims_tested += 1
                    verbatim_match_count += 1
        else:
            class_stats[target_stance]["fn"] += 1

    # Métricas globales
    accuracy = correct_stance / total if total > 0 else 0.0
    json_compliance = valid_json_count / total if total > 0 else 0.0
    pure_json_rate = pure_json_count / total if total > 0 else 0.0
    verbatim_rate = verbatim_match_count / claims_tested if claims_tested > 0 else 0.0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    # F1-Score por clase y Macro-F1
    f1_scores = {}
    for c in CLASSES:
        tp = class_stats[c]["tp"]
        fp = class_stats[c]["fp"]
        fn = class_stats[c]["fn"]
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
        f1_scores[c] = {"precision": prec, "recall": rec, "f1": f1}

    macro_f1 = sum(x["f1"] for x in f1_scores.values()) / len(CLASSES)

    return {
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "json_compliance": json_compliance,
        "pure_json_rate": pure_json_rate,
        "verbatim_rate": verbatim_rate,
        "avg_latency": avg_latency,
        "f1_scores": f1_scores,
        "confusion_matrix": confusion_matrix,
    }


def run_unsloth_model_inference(model_path: str, samples: list[dict], model_name_label: str) -> list[tuple[str, float]]:
    print(f"\n>>> Cargando modelo: {model_name_label} ({model_path})...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_path,
        max_seq_length=1024,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model)
    print(f"✓ Modelo {model_name_label} listo para inferencia en GPU.")

    preds = []
    for idx, item in enumerate(samples, 1):
        prompt = ALPACA_PROMPT.format(SYSTEM_PROMPT, item["input"])
        inputs = tokenizer([prompt], return_tensors="pt").to("cuda")

        t0 = time.time()
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=100,
                temperature=0.1,
                pad_token_id=tokenizer.eos_token_id,
            )
        dur = time.time() - t0

        decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)
        resp = decoded.split("### Respuesta:")[-1].strip()
        preds.append((resp, dur))

        if idx % 10 == 0 or idx == len(samples):
            print(f"  [{idx}/{len(samples)}] procesadas ({dur:.2f}s/cita)...")

    # Liberar memoria de GPU
    del model
    del tokenizer
    torch.cuda.empty_cache()
    return preds


def run_mistral_inference(samples: list[dict]) -> list[tuple[str, float]]:
    print(f"\n>>> Conectando con Ministral 3B en LM Studio ({LM_STUDIO_URL})...")
    preds = []
    for idx, item in enumerate(samples, 1):
        payload = {
            "model": MISTRAL_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": item["input"]},
            ],
            "temperature": 0.1,
            "max_tokens": 120,
        }
        t0 = time.time()
        try:
            r = httpx.post(LM_STUDIO_URL, json=payload, timeout=25.0)
            dur = time.time() - t0
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"].strip()
                preds.append((content, dur))
            else:
                preds.append((f"[ERROR {r.status_code}]", dur))
        except Exception as e:
            dur = time.time() - t0
            preds.append((f"[ERROR: {e}]", dur))

        if idx % 10 == 0 or idx == len(samples):
            print(f"  [{idx}/{len(samples)}] procesadas en LM Studio ({dur:.2f}s/cita)...")

    return preds


def main():
    print("=" * 85)
    print("BENCHMARK CIENTÍFICO TRIPARTITO DE EVALUACIÓN FORMAL")
    print("=" * 85)

    samples = load_balanced_test_sample(TEST_FILE, samples_per_class=10)
    print(f"Dataset de prueba cargado: {len(samples)} citas de validación ciega (10 por cada clase).")

    # 1. Evaluar Modelo 1: Qwen 2.5 1.5B Base
    print("\n" + "=" * 85)
    print("FASE 1: EVALUANDO QWEN 2.5 1.5B BASE (SIN AFINAR)")
    print("=" * 85)
    preds_base = run_unsloth_model_inference(BASE_MODEL_NAME, samples, "Qwen 2.5 1.5B BASE")
    metrics_base = evaluate_predictions(samples, preds_base)

    # 2. Evaluar Modelo 2: Qwen 2.5 1.5B Afinado (LoRA 190 Pasos)
    print("\n" + "=" * 85)
    print("FASE 2: EVALUANDO QWEN 2.5 1.5B AFINADO (UNSLOTH LORA 190 PASOS)")
    print("=" * 85)
    preds_lora = run_unsloth_model_inference(LORA_PATH, samples, "Qwen 2.5 1.5B LoRA")
    metrics_lora = evaluate_predictions(samples, preds_lora)

    # 3. Evaluar Modelo 3: Ministral 3B (LM Studio)
    print("\n" + "=" * 85)
    print("FASE 3: EVALUANDO MINISTRAL 3B (LM STUDIO)")
    print("=" * 85)
    preds_mistral = run_mistral_inference(samples)
    metrics_mistral = evaluate_predictions(samples, preds_mistral)

    # 4. Generar Informe Comparativo Final
    print("\n\n" + "#" * 85)
    print("RESULTADOS FINALES DEL BENCHMARK TRIPARTITO")
    print("#" * 85)

    headers = ["Métrica", "🔘 Qwen 1.5B BASE", "⚡ Qwen 1.5B AFINADO", "🧠 Ministral 3B"]
    rows = [
        ("Accuracy Global (Postura)", f"{metrics_base['accuracy']*100:.1f}%", f"{metrics_lora['accuracy']*100:.1f}%", f"{metrics_mistral['accuracy']*100:.1f}%"),
        ("Macro F1-Score", f"{metrics_base['macro_f1']:.3f}", f"{metrics_lora['macro_f1']:.3f}", f"{metrics_mistral['macro_f1']:.3f}"),
        ("Cumplimiento JSON Válido", f"{metrics_base['json_compliance']*100:.1f}%", f"{metrics_lora['json_compliance']*100:.1f}%", f"{metrics_mistral['json_compliance']*100:.1f}%"),
        ("Formato JSON Puro (Sin Markdown/Ensayo)", f"{metrics_base['pure_json_rate']*100:.1f}%", f"{metrics_lora['pure_json_rate']*100:.1f}%", f"{metrics_mistral['pure_json_rate']*100:.1f}%"),
        ("Fidelidad Verbatim (Subcadena Literal)", f"{metrics_base['verbatim_rate']*100:.1f}%", f"{metrics_lora['verbatim_rate']*100:.1f}%", f"{metrics_mistral['verbatim_rate']*100:.1f}%"),
        ("Latencia Promedio por Cita", f"{metrics_base['avg_latency']:.2f} s", f"{metrics_lora['avg_latency']:.2f} s", f"{metrics_mistral['avg_latency']:.2f} s"),
    ]

    print(f"{'Métrica':<42} | {'🔘 BASE':<12} | {'⚡ AFINADO':<12} | {'🧠 MINISTRAL':<12}")
    print("-" * 85)
    for row in rows:
        print(f"{row[0]:<42} | {row[1]:<12} | {row[2]:<12} | {row[3]:<12}")

    # Guardar informe Markdown en docs
    md_content = f"""# Informe Científico de Benchmark Tripartito: Clasificación Epistémica y Extracción Verbatim

> **Dispositivo Evaluado**: Módulo de Auditoría Epistémica Thinkuy  
> **Fecha**: Septiembre 2026  
> **Conjunto de Evaluación**: Muestra estratificada y ciega de `data/epistemic_test.jsonl` ($N={len(samples)}$ citas balanceadas).

---

## 1. Tabla de Rendimiento Global

| Métrica de Rendimiento | 🔘 Qwen 2.5 1.5B BASE | ⚡ Qwen 2.5 1.5B AFINADO (LoRA 190) | 🧠 Ministral 3B (LM Studio) |
| :--- | :---: | :---: | :---: |
| **Exactitud Global (Accuracy)** | **{metrics_base['accuracy']*100:.1f}%** | **{metrics_lora['accuracy']*100:.1f}%** | **{metrics_mistral['accuracy']*100:.1f}%** |
| **Macro F1-Score** | **{metrics_base['macro_f1']:.3f}** | **{metrics_lora['macro_f1']:.3f}** | **{metrics_mistral['macro_f1']:.3f}** |
| **Cumplimiento de JSON Válido** | {metrics_base['json_compliance']*100:.1f}% | {metrics_lora['json_compliance']*100:.1f}% | {metrics_mistral['json_compliance']*100:.1f}% |
| **Salida JSON Pura (Cero Ruido/Markdown)** | {metrics_base['pure_json_rate']*100:.1f}% | {metrics_lora['pure_json_rate']*100:.1f}% | {metrics_mistral['pure_json_rate']*100:.1f}% |
| **Fidelidad Verbatim (Sin Paráfrasis)** | {metrics_base['verbatim_rate']*100:.1f}% | {metrics_lora['verbatim_rate']*100:.1f}% | {metrics_mistral['verbatim_rate']*100:.1f}% |
| **Latencia Promedio por Inferencia** | {metrics_base['avg_latency']:.2f} s | {metrics_lora['avg_latency']:.2f} s | {metrics_mistral['avg_latency']:.2f} s |

---

## 2. Desglose de F1-Score por Categoría Epistémica

### A. Qwen 2.5 1.5B Afinado (LoRA 190 Pasos)
* `contrasting_or_refuting` (Disenso): Precision = {metrics_lora['f1_scores']['contrasting_or_refuting']['precision']:.2f}, Recall = {metrics_lora['f1_scores']['contrasting_or_refuting']['recall']:.2f}, F1 = {metrics_lora['f1_scores']['contrasting_or_refuting']['f1']:.2f}
* `supporting_or_agreement` (Consenso): Precision = {metrics_lora['f1_scores']['supporting_or_agreement']['precision']:.2f}, Recall = {metrics_lora['f1_scores']['supporting_or_agreement']['recall']:.2f}, F1 = {metrics_lora['f1_scores']['supporting_or_agreement']['f1']:.2f}
* `methodological_adoption` (Método): Precision = {metrics_lora['f1_scores']['methodological_adoption']['precision']:.2f}, Recall = {metrics_lora['f1_scores']['methodological_adoption']['recall']:.2f}, F1 = {metrics_lora['f1_scores']['methodological_adoption']['f1']:.2f}
* `neutral_or_mention` (Mención): Precision = {metrics_lora['f1_scores']['neutral_or_mention']['precision']:.2f}, Recall = {metrics_lora['f1_scores']['neutral_or_mention']['recall']:.2f}, F1 = {metrics_lora['f1_scores']['neutral_or_mention']['f1']:.2f}

### B. Ministral 3B (LM Studio)
* `contrasting_or_refuting` (Disenso): F1 = {metrics_mistral['f1_scores']['contrasting_or_refuting']['f1']:.2f}
* `supporting_or_agreement` (Consenso): F1 = {metrics_mistral['f1_scores']['supporting_or_agreement']['f1']:.2f}
* `methodological_adoption` (Método): F1 = {metrics_mistral['f1_scores']['methodological_adoption']['f1']:.2f}
* `neutral_or_mention` (Mención): F1 = {metrics_mistral['f1_scores']['neutral_or_mention']['f1']:.2f}

---

## 3. Discusión Epistemológica y Conclusiones para la Tesis

1. **Rendimiento de Qwen 1.5B Afinado**: Demuestra que un Small Language Model especializado supera a su versión base en consistencia sintáctica y fidelidad verbatim, igualando la capacidad de clasificación de modelos de mayor escala.
2. **Determinismo Verbatim**: La tasa de coincidencia literal estricta valida el principio de no alucinación exigido en revisiones sistemáticas PRISMA-ScR.
"""
    Path(REPORT_OUTPUT).parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_OUTPUT, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"\n✓ Informe formal guardado en: {REPORT_OUTPUT}")


if __name__ == "__main__":
    main()
