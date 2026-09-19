"""Script de Evaluación y Comparación del Modelo Epistémico Qwen 2.5 1.5B Afinado.

Carga los adaptadores LoRA entrenados (Paso 190 / Época 2.0) y ejecuta pruebas cualitativas
en vivo contra citas de Consenso, Disenso, Adopción Metodológica y Mención Contextual.
"""
import os
import sys
import json
from pathlib import Path
import torch
from unsloth import FastLanguageModel

LORA_PATH = r"C:\Users\gipsy\.unsloth\studio\outputs\unsloth_Qwen2.5-1.5B-Instruct-bnb-4bit__project-thinkuy-epistemic-qwen_1789479572"
MAX_SEQ_LENGTH = 1024

print("=" * 80)
print("EVALUACIÓN CUALITATIVA EN VIVO — QWEN 2.5 1.5B FINE-TUNED (PASO 190 / 2 ÉPOCAS)")
print("=" * 80)

print("\n[1/2] Cargando modelo base y activando adaptadores LoRA afinados...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=LORA_PATH,
    max_seq_length=MAX_SEQ_LENGTH,
    dtype=None,
    load_in_4bit=True,
)
FastLanguageModel.for_inference(model)
print("✓ Modelo cargado en modo inferencia acelerada.")

ALPACA_PROMPT = """A continuación se presenta una instrucción que describe una tarea, junto con una entrada que proporciona más contexto. Escribe una respuesta que complete adecuadamente la solicitud.

### Instrucción:
{}

### Entrada:
{}

### Respuesta:
"""

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

TEST_CASES = [
    {
        "name": "CASO 1: DISENSO / REFUTACIÓN EXPLÍCITA",
        "input": "Contexto de citación: \"Sin embargo, a diferencia de los resultados reportados por Gómez et al. (2021), nuestros experimentos no encontraron una correlación estadísticamente significativa entre ambas variables.\"\nSección: Discusión",
        "expected": "contrasting_or_refuting",
    },
    {
        "name": "CASO 2: CONSENSO / APOYO Y CORROBORACIÓN",
        "input": "Contexto de citación: \"En concordancia con los hallazgos de Mendoza (2022), nuestros datos empíricos confirman la hipótesis de una reducción notable del error basal.\"\nSección: Resultados y Discusión",
        "expected": "supporting_or_agreement",
    },
    {
        "name": "CASO 3: ADOPCIÓN METODOLÓGICA",
        "input": "Contexto de citación: \"Para la recolección de los datos empíricos se adaptó el cuestionario de competencia digital docente desarrollado y validado por Cabero y Palacios (2020).\"\nSección: Metodología",
        "expected": "methodological_adoption",
    },
    {
        "name": "CASO 4: MENCIÓN CONTEXTUAL / ANTECEDENTES",
        "input": "Contexto de citación: \"El concepto de gobernanza epistémica ha sido objeto de creciente atención en la literatura sociológica contemporánea (Valenzuela, 2014; Torres, 2018; Castro, 2021).\"\nSección: Introducción",
        "expected": "neutral_or_mention",
    },
    {
        "name": "CASO 5: DISENSO BIOMÉDICO EN INGLÉS",
        "input": "Contexto de citación: \"In contrast to previous findings reported by Smith et al. (2019), our clinical trials failed to demonstrate any significant improvement in patient recovery time.\"\nSección: Discussion",
        "expected": "contrasting_or_refuting",
    },
]

print("\n" + "=" * 80)
print("EJECUTANDO PRUEBAS DE INFERENCIA EN VIVO")
print("=" * 80)

for i, tc in enumerate(TEST_CASES, 1):
    prompt = ALPACA_PROMPT.format(SYSTEM_PROMPT, tc["input"])
    inputs = tokenizer([prompt], return_tensors="pt").to("cuda")

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=128,
            use_cache=True,
            pad_token_id=tokenizer.eos_token_id,
            temperature=0.1,  # Inferencia determinista
        )

    decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)
    # Extraer respuesta tras "### Respuesta:"
    resp_part = decoded.split("### Respuesta:")[-1].strip()

    print(f"\n--- [{i}/{len(TEST_CASES)}] {tc['name']} ---")
    print(f"Esperado: {tc['expected']}")
    print(f"Predicción del Modelo Afinado:")
    print(resp_part)

print("\n" + "=" * 80)
print("¡EVALUACIÓN COMPLETADA!")
print("=" * 80)
