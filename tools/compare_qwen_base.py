"""Evaluación de Qwen 2.5 1.5B BASE (Sin Fine-Tuning / Sin Adaptadores LoRA)
sobre las mismas 6 tareas académicas de Thinkuy.
"""
import os
import sys
import time
import json
import torch
from unsloth import FastLanguageModel

BASE_MODEL = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"

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

TEST_CASES = [
    {
        "id": 1,
        "titulo": "Disenso / Refutación Empírica (Español)",
        "entrada": "Contexto de citación: \"Sin embargo, a diferencia de los resultados reportados por Gómez et al. (2021), nuestros experimentos no encontraron una correlación estadísticamente significativa entre ambas variables.\"\nSección: Discusión",
        "esperado": "contrasting_or_refuting",
    },
    {
        "id": 2,
        "titulo": "Consenso y Corroboración (Español)",
        "entrada": "Contexto de citación: \"En concordancia con los hallazgos de Mendoza (2022), nuestros datos empíricos confirman de forma categórica la hipótesis de reducción del error basal.\"\nSección: Resultados",
        "esperado": "supporting_or_agreement",
    },
    {
        "id": 3,
        "titulo": "Adopción Metodológica (Español)",
        "entrada": "Contexto de citación: \"Para la recolección de los datos empíricos se adaptó el cuestionario de competencia digital docente desarrollado y validado por Cabero y Palacios (2020).\"\nSección: Metodología",
        "esperado": "methodological_adoption",
    },
    {
        "id": 4,
        "titulo": "Mención Contextual de Antecedentes (Español)",
        "entrada": "Contexto de citación: \"El concepto de gobernanza epistémica ha sido objeto de creciente atención en la literatura sociológica contemporánea (Valenzuela, 2014; Torres, 2018; Castro, 2021).\"\nSección: Introducción",
        "esperado": "neutral_or_mention",
    },
    {
        "id": 5,
        "titulo": "Disenso Clínico en Inglés",
        "entrada": "Contexto de citación: \"In contrast to previous findings reported by Smith et al. (2019), our clinical trials failed to demonstrate any significant improvement in patient recovery time.\"\nSección: Discussion",
        "esperado": "contrasting_or_refuting",
    },
    {
        "id": 6,
        "titulo": "Párrafo Complejo con Tensión Retórica",
        "entrada": "Contexto de citación: \"Si bien los trabajos de Silva (2019) proveyeron el marco teórico inicial, nuestra evidencia longitudinal nos obliga a refutar frontalmente los postulados de Fernández y Ruiz (2020) sobre la estabilidad institucional.\"\nSección: Discusión",
        "esperado": "contrasting_or_refuting",
    },
]


def main():
    print("=" * 85)
    print("EVALUACIÓN EN VIVO: QWEN 2.5 1.5B BASE (SIN ADAPTADORES / ZERO-SHOT)")
    print("=" * 85)

    print("\n[1/2] Cargando Qwen 2.5 1.5B Base original...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=1024,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model)
    print("✓ Modelo Base listo en VRAM.")

    print("\n[2/2] Ejecutando las 6 pruebas académicas sobre el modelo Base...")

    for tc in TEST_CASES:
        print("\n" + "=" * 85)
        print(f"📌 PRUEBA {tc['id']}: {tc['titulo']}")
        print(f"🎯 Postura Esperada: {tc['esperado']}")
        print("=" * 85)

        prompt = ALPACA_PROMPT.format(SYSTEM_PROMPT, tc["entrada"])
        inputs = tokenizer([prompt], return_tensors="pt").to("cuda")

        t0 = time.time()
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=150,
                temperature=0.1,
                pad_token_id=tokenizer.eos_token_id,
            )
        dur = time.time() - t0

        decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)
        resp = decoded.split("### Respuesta:")[-1].strip()

        print(f"\n🔘 [Qwen 2.5 1.5B BASE] (Tiempo: {dur:.2f}s):")
        print(resp)

    print("\n" + "=" * 85)
    print("¡EVALUACIÓN DEL MODELO BASE COMPLETADA!")
    print("=" * 85)


if __name__ == "__main__":
    main()
