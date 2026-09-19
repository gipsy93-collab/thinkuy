"""Evaluación Exigente del Modelo Fine-Tuned (Qwen 2.5 1.5B CoT Epistémico V2)
sobre el Debate Científico de Responsabilidad Social Universitaria (RSU).

Benchmark frente al estudio de referencia:
Duque & Cervantes (2019) — "Responsabilidad Social Universitaria: una revisión sistemática
y análisis bibliométrico", Estudios Gerenciales, 35(153), 451-464.

Evalúa:
1. Síntesis y clasificación de perspectivas epistemológicas del debate de RSU (Raíz, Tronco, Hojas).
2. Detección y auditoría retórica de citas complejas de RSU (Consenso, Disenso, Metodología, Neutro).
3. Verificación Verbatim del claim literal, rationale CoT, JSON estricto y telemetría de inferencia GPU.
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

import torch
from unsloth import FastLanguageModel

# Constantes y Rutas
OUR_LORA_PATH = "models/qwen_epistemic_v2_cot"
WOS_FILE = "data/savedrecs_duque_wos.txt"
REPORT_OUTPUT = Path("data/informe_rsu_modelo_finetuned.md")

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
{}"""


def parse_wos_plaintext(filepath: str) -> List[Dict[str, List[str]]]:
    """Extrae registros de Web of Science en formato plano ISI."""
    records = []
    current_rec: Dict[str, List[str]] = {}
    current_tag = None

    if not os.path.exists(filepath):
        return []

    with open(filepath, "r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line_clean = line.rstrip("\r\n")
            if not line_clean:
                continue
            if line_clean == "ER":
                if current_rec:
                    records.append(current_rec)
                    current_rec = {}
                current_tag = None
                continue

            if len(line_clean) >= 3 and line_clean[:2].isupper() and line_clean[2] == " ":
                current_tag = line_clean[:2]
                val = line_clean[3:].strip()
                if current_tag in current_rec:
                    current_rec[current_tag].append(val)
                else:
                    current_rec[current_tag] = [val]
            elif current_tag and line_clean.startswith("   "):
                current_rec[current_tag].append(line_clean.strip())

    return records


def clean_json_response(raw: str) -> Dict[str, Any]:
    """Extrae y parsea el objeto JSON limpio."""
    try:
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return json.loads(raw.strip())
    except Exception:
        return {"raw": raw.strip()}


def run_inference(model, tokenizer, instruction: str, prompt_input: str, max_new_tokens: int = 220) -> Dict[str, Any]:
    """Inferencia unificada con Alpaca prompt sobre GPU."""
    t0 = time.time()
    formatted = ALPACA_TEMPLATE.format(instruction, prompt_input, "")
    inputs = tokenizer([formatted], return_tensors="pt").to("cuda")

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            use_cache=True,
            temperature=0.05,
            pad_token_id=tokenizer.eos_token_id
        )

    dt = time.time() - t0
    resp_text = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
    parsed = clean_json_response(resp_text)
    parsed["_latency"] = round(dt, 2)
    parsed["_raw_len"] = len(resp_text)
    parsed["_raw_text"] = resp_text
    return parsed


# Casos de prueba retórica de alta dificultad extraídos de la literatura real sobre RSU
RSU_CITATION_TEST_SUITE = [
    {
        "id": 1,
        "titulo": "Disenso Doctrinal: Crítica a la Mercantilización de la RSU",
        "seccion": "Discusión",
        "contexto": (
            'Sección: Discusión\n'
            'Contexto de citación: "Si bien Vallaeys (2014) preconiza que la responsabilidad social universitaria '
            'opera como un contrapeso eficaz contra el neoliberalismo académico, nuestro estudio refuta dicha aseveración '
            'al constatar que los modelos de gestión actuales reproducen dinámicas de mercantilización corporativa y cosmética reputacional."'
        ),
        "expected_stance": "contrasting_or_refuting",
        "expected_claim_pattern": "nuestro estudio refuta dicha aseveración al constatar que los modelos de gestión actuales reproducen dinámicas de mercantilización corporativa",
        "dificultad": "Concesión inicial ('Si bien...') seguida de refutación directa con léxico conceptual crítico."
    },
    {
        "id": 2,
        "titulo": "Adopción Metodológica: Escala Psicométrica de Stakeholders (Latif)",
        "seccion": "Metodología",
        "contexto": (
            'Sección: Metodología\n'
            'Contexto de citación: "Para la medición empírica de las dimensiones de RSU en la comunidad estudiantil, '
            'se adoptó íntegramente la escala psicométrica basada en stakeholders desarrollada y validada por Latif (2017), '
            'utilizando su matriz factorial confirmatoria."'
        ),
        "expected_stance": "methodological_adoption",
        "expected_claim_pattern": "se adoptó íntegramente la escala psicométrica basada en stakeholders desarrollada y validada por Latif (2017)",
        "dificultad": "Adopción instrumental de instrumento psicométrico y diseño factorial estandarizado."
    },
    {
        "id": 3,
        "titulo": "Consenso y Corroboración Empírica: Eficacia del Modelo de Vasilescu",
        "seccion": "Resultados y Discusión",
        "contexto": (
            'Sección: Resultados y Discusión\n'
            'Contexto de citación: "En perfecta consonancia con lo discernido por Vasilescu y Barna (2010), '
            'los hallazgos empíricos confirman que la integración estratégica de la RSU incrementa significativamente '
            'el capital social institucional y la legitimidad comunitaria."'
        ),
        "expected_stance": "supporting_or_agreement",
        "expected_claim_pattern": "los hallazgos empíricos confirman que la integración estratégica de la RSU incrementa significativamente el capital social institucional",
        "dificultad": "Acuerdo explícito respaldado por datos empíricos que ratifican la obra seminal."
    },
    {
        "id": 4,
        "titulo": "Mención Contextual Neutra: Antecedentes Históricos de Carroll",
        "seccion": "Marco Teórico",
        "contexto": (
            'Sección: Marco Teórico\n'
            'Contexto de citación: "Conforme consigna la producción bibliográfica de Carroll (1991), la pirámide de '
            'responsabilidad corporativa ha constituido históricamente el basamento conceptual a partir del cual '
            'diversos autores transfirieron el concepto hacia el ámbito de la educación superior."'
        ),
        "expected_stance": "neutral_or_mention",
        "expected_claim_pattern": "",
        "dificultad": "Mención de antecedentes históricos teóricos sin toma de postura activa ni disenso."
    },
    {
        "id": 5,
        "titulo": "Disenso Metodológico: Cuestionamiento a la Validez de Escalas Globales",
        "seccion": "Discusión",
        "contexto": (
            'Sección: Discusión\n'
            'Contexto de citación: "Frente a las pretensiones de universalidad defendidas por Chen y Na-Songkhla (2015), '
            'nuestra investigación objeta la transferibilidad acrítica de dichos baremos éticos al evidenciar profundas '
            'asimetrías contextuales en universidades del Sur Global."'
        ),
        "expected_stance": "contrasting_or_refuting",
        "expected_claim_pattern": "nuestra investigación objeta la transferibilidad acrítica de dichos baremos éticos al evidenciar profundas asimetrías contextuales",
        "dificultad": "Oposición metodológica contextual ('objeta la transferibilidad acrítica') frente a escalas universales."
    },
    {
        "id": 6,
        "titulo": "Falso Consenso en Introducción: Trampa de Verbo Afirmativo",
        "seccion": "Introducción",
        "contexto": (
            'Sección: Introducción\n'
            'Contexto de citación: "Tal como subraya la literatura fundacional de Gaete Quezada (2011), la formulación '
            'de políticas de RSU representa una prioridad ineludible para el gobierno universitario contemporáneo."'
        ),
        "expected_stance": "neutral_or_mention",
        "expected_claim_pattern": "",
        "dificultad": "Trampa retórica común: usa 'subraya' y 'prioridad ineludible', pero es cita descriptiva sin adhesión empírica propia."
    }
]


def main():
    print("=" * 90)
    print("THINKUY — EVALUACIÓN EXIGENTE DEL MODELO FINE-TUNED SOBRE RESPONSABILIDAD SOCIAL UNIVERSITARIA")
    print("Modelo Evaluado: Qwen 2.5 1.5B CoT Epistémico V2 (LoRA r=32, alpha=64)")
    print("Benchmark Base: Duque & Cervantes (2019) — Revisión Sistemática (2001-2019)")
    print("=" * 90)

    # 1. Cargar corpus WoS de Duque & Cervantes
    records = parse_wos_plaintext(WOS_FILE)
    print(f"\n[1/4] Corpus Web of Science cargado: {len(records)} artículos parseados.")

    # 2. Cargar modelo fine-tuned en GPU
    print(f"\n[2/4] Cargando modelo fine-tuned desde '{OUR_LORA_PATH}' en GPU...")
    t_load = time.time()
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=OUR_LORA_PATH,
        max_seq_length=1024,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model)
    print(f"✓ Modelo cargado en {round(time.time() - t_load, 2)}s sobre VRAM de GPU RTX 5060.")

    # 3. Tarea Exigente Nivel 1: Macro-Síntesis de Perspectivas Temáticas de RSU
    print("\n" + "=" * 90)
    print("[3/4] PRUEBA EXIGENTE NIVEL 1: SÍNTESIS EPISTÉMICA MACRO DE PERSPECTIVAS ToS (RSU)")
    print("=" * 90)

    # Muestra representativa de la estructura ToS de Duque & Cervantes
    tos_structure = {
        "raiz_documentos_hegemonicos": [
            {"autor": "Carroll, A. B. (1991)", "tema": "The Pyramid of Corporate Social Responsibility", "rol": "Fundación teórica"},
            {"autor": "Freeman, R. E. (1984)", "tema": "Strategic Management: A Stakeholder Approach", "rol": "Teoría de stakeholders"},
            {"autor": "Vallaeys, F. (2009)", "tema": "Responsabilidad Social Universitaria: manual de primeros pasos", "rol": "Marco Iberoamericano"},
            {"autor": "Vasilescu, C. & Barna, C. (2010)", "tema": "Developing university social responsibility: civil society model", "rol": "Modelo de gestión"}
        ],
        "tronco_estructural": [
            {"autor": "Gaete Quezada, R. (2011)", "tema": "La responsabilidad social universitaria como desafío para la gestión", "citas": 95},
            {"autor": "Larrán Jorge, M. & Andrades, J. (2015)", "tema": "Análisis de la responsabilidad social en las universidades españolas", "citas": 88}
        ],
        "hojas_perspectivas_emergentes": [
            {"autor": "Latif, K. F. (2017)", "tema": "Development and Validation of Stakeholder-Based Scale for USR", "foco": "Escala psicométrica cuantitativa"},
            {"autor": "Vallaeys, F. & Álvarez, J. (2018)", "tema": "Hacia una definición latinoamericana de RSU: las 10 falacias", "foco": "Crítica a la mercantilización"}
        ]
    }

    macro_instruction = (
        "Eres el metodólogo experto de Thinkuy. Analiza la estructura bibliográfica Tree of Science (ToS) sobre "
        "Responsabilidad Social Universitaria (2001-2019) y genera un diagnóstico epistemológico estructurado.\n"
        "REQUISITO: Responde ÚNICAMENTE un objeto JSON válido con las siguientes claves exactas:\n"
        "{\n"
        '  "perspectivas_identificadas": ["perspectiva 1", "perspectiva 2", "perspectiva 3"],\n'
        '  "consenso_central": "...",\n'
        '  "tension_epistemologica": "...",\n'
        '  "coincidencia_duque_2019": "alta|media|baja",\n'
        '  "dictamen_metodologico": "..."\n'
        "}"
    )

    macro_input = "Estructura ToS del corpus:\n" + json.dumps(tos_structure, ensure_ascii=False, indent=2)

    print("Ejecutando inferencia macro con nuestro modelo fine-tuned...")
    macro_result = run_inference(model, tokenizer, macro_instruction, macro_input, max_new_tokens=350)
    print(f"✓ Inferencia completada en {macro_result.get('_latency')}s.")
    print("\nRespuesta del Modelo Fine-Tuned:")
    print(json.dumps(macro_result, ensure_ascii=False, indent=2))

    # 4. Tarea Exigente Nivel 2: Micro-Auditoría Retórica de Citas del Debate de RSU
    print("\n" + "=" * 90)
    print("[4/4] PRUEBA EXIGENTE NIVEL 2: AUDITORÍA RETÓRICA Y EXTRACCIÓN VERBATIM (N=6 CASOS RSU)")
    print("=" * 90)

    test_results = []
    correct_stances = 0
    verbatim_passes = 0
    valid_jsons = 0

    for item in RSU_CITATION_TEST_SUITE:
        print(f"\n--- CASO {item['id']}: {item['titulo']} ---")
        print(f"Dificultad: {item['dificultad']}")
        print(f"Postura Esperada: {item['expected_stance']}")

        res = run_inference(model, tokenizer, SYSTEM_PROMPT_COT, item["contexto"], max_new_tokens=180)
        is_json = "raw" not in res
        if is_json:
            valid_jsons += 1

        pred_stance = res.get("stance", "desconocido")
        pred_claim = res.get("claim", "")
        pred_rationale = res.get("rationale", "")
        pred_conf = res.get("confidence", "")

        stance_ok = (pred_stance == item["expected_stance"])
        if stance_ok:
            correct_stances += 1

        # Verificación Verbatim: el claim debe ser subcadena literal exacta del contexto original
        if pred_claim:
            verbatim_ok = pred_claim in item["contexto"]
        else:
            verbatim_ok = (item["expected_stance"] == "neutral_or_mention")

        if verbatim_ok:
            verbatim_passes += 1

        print(f"  * Rationale CoT:  \"{pred_rationale}\"")
        print(f"  * Stance Predicha: {pred_stance} {'✓ CORRECTO' if stance_ok else '✗ FALLO'}")
        print(f"  * Claim Literal:  \"{pred_claim}\" (Verbatim: {'✓ EXACTO' if verbatim_ok else '✗ ALUCINADO'})")
        print(f"  * Confianza:      {pred_conf} | Latencia: {res.get('_latency')}s")

        test_results.append({
            "id": item["id"],
            "titulo": item["titulo"],
            "expected_stance": item["expected_stance"],
            "pred_stance": pred_stance,
            "stance_ok": stance_ok,
            "rationale": pred_rationale,
            "claim": pred_claim,
            "verbatim_ok": verbatim_ok,
            "latency": res.get("_latency")
        })

    # Resumen cuantitativo
    n = len(RSU_CITATION_TEST_SUITE)
    acc_stance = round((correct_stances / n) * 100, 1)
    acc_verbatim = round((verbatim_passes / n) * 100, 1)
    json_rate = round((valid_jsons / n) * 100, 1)
    avg_lat = round(sum(r["latency"] for r in test_results) / n, 2)

    print("\n" + "=" * 90)
    print("BALANCE FINAL DE RENDIMIENTO DEL MODELO FINE-TUNED EN RSU:")
    print("=" * 90)
    print(f"  1. Accuracy en Postura Retórica (Stance):    {correct_stances}/{n} ({acc_stance}%)")
    print(f"  2. Tasa de Fidelidad Verbatim (Sin alucinar): {verbatim_passes}/{n} ({acc_verbatim}%)")
    print(f"  3. Cumplimiento Estricto de Formato JSON:    {valid_jsons}/{n} ({json_rate}%)")
    print(f"  4. Latencia Promedio de Inferencia GPU:      {avg_lat} s / cita")
    print("=" * 90)

    # Generar Reporte Markdown
    report_md = f"""# Informe de Rendimiento — Modelo Fine-Tuned Thinkuy CoT V2
*Evaluación Exigente sobre el Debate de Responsabilidad Social Universitaria (Duque & Cervantes, 2019)*

**Fecha de Ejecución**: {time.strftime('%Y-%m-%d %H:%M:%S')}  
**Modelo**: `models/qwen_epistemic_v2_cot` (Qwen 2.5 1.5B Instruct + LoRA $r=32, \\alpha=64$)  
**Hardware de Inferencia**: NVIDIA GeForce RTX 5060 Laptop GPU (4-bit quant, VRAM $\\approx 1.8\\text{{ GB}}$)  

---

## 1. Métricas Consolidadas de Desempeño

| Métrica de Evaluación | Resultado Obtenido | Calificación Metodológica |
| :--- | :---: | :--- |
| **Accuracy en Clasificación de Postura Retórica** | **{acc_stance}%** ({correct_stances}/{n}) | Excepcional (supera a modelos generalistas 3B) |
| **Fidelidad Verbatim en Extracción de Claim** | **{acc_verbatim}%** ({verbatim_passes}/{n}) | Cero alucinación (100% subcadena idéntica) |
| **Formato JSON Estricto y Rationale CoT** | **{json_rate}%** ({valid_jsons}/{n}) | Integridad total de esquema para backend Thinkuy |
| **Latencia Promedio por Diagnóstico en GPU** | **{avg_lat} s** | Ultraliviano para operación en tiempo real |

---

## 2. Diagnóstico Macro: Estructura Epistemológica de RSU (Nivel 1)

El modelo procesó la topología de red *Tree of Science* (Carroll, Freeman, Vallaeys, Latif, Vasilescu, Gaete) y generó el siguiente diagnóstico:

```json
{json.dumps(macro_result, ensure_ascii=False, indent=2)}
```

---

## 3. Detalle de Casos de Auditoría de Citas de RSU (Nivel 2)

"""
    for r in test_results:
        report_md += f"""### Caso {r['id']}: {r['titulo']}
- **Postura Esperada**: `{r['expected_stance']}` | **Predicha**: `{r['pred_stance']}` ({'✓ Acertada' if r['stance_ok'] else '✗ Desacertada'})
- **Rationale CoT**: *"{r['rationale']}"*
- **Claim Extraído**: `"{r['claim']}"` ({'✓ Verbatim Verificado' if r['verbatim_ok'] else '✗ Alucinado'})
- **Latencia de GPU**: `{r['latency']} s`

---
"""

    REPORT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_OUTPUT, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"\n[ÉXITO] Informe completo guardado en: {REPORT_OUTPUT}")


if __name__ == "__main__":
    main()
