"""Script de Benchmark y Comparación Lado a Lado:
Qwen 2.5 1.5B Fine-Tuned (Unsloth LoRA 190 Pasos) VS Mistral / Ministral 3B (LM Studio API :1234)
"""
import os
import sys
import time
import json
import httpx
import torch
from unsloth import FastLanguageModel

# Configuración
LORA_PATH = r"C:\Users\gipsy\.unsloth\studio\outputs\unsloth_Qwen2.5-1.5B-Instruct-bnb-4bit__project-thinkuy-epistemic-qwen_1789479572"
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MISTRAL_MODEL = "mistralai/ministral-3-3b"

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


def query_mistral_lm_studio(tc):
    start = time.time()
    payload = {
        "model": MISTRAL_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": tc["entrada"]},
        ],
        "temperature": 0.1,
        "max_tokens": 150,
    }
    try:
        r = httpx.post(LM_STUDIO_URL, json=payload, timeout=20.0)
        dur = time.time() - start
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"].strip()
            return content, dur
        else:
            return f"[ERROR {r.status_code}]: {r.text}", dur
    except Exception as e:
        dur = time.time() - start
        return f"[EXCEPCIÓN LM STUDIO]: {e}", dur


def main():
    print("=" * 85)
    print("BENCHMARK CIENTÍFICO LADO A LADO: QWEN 2.5 1.5B (AFINADO) vs MINISTRAL 3B")
    print("=" * 85)

    print("\n[1/3] Cargando Qwen 2.5 1.5B Afinado con LoRA (Unsloth)...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=LORA_PATH,
        max_seq_length=1024,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model)
    print("✓ Qwen 2.5 1.5B listo en VRAM.")

    print(f"\n[2/3] Verificando conexión con Ministral 3B en LM Studio (:1234)...")
    try:
        test_r = httpx.get("http://127.0.0.1:1234/v1/models", timeout=3.0)
        print(f"✓ LM Studio activo. Modelos disponibles: {[m['id'] for m in test_r.json().get('data', [])]}")
    except Exception as e:
        print(f"⚠️ LM Studio no respondió en :1234: {e}")

    print("\n[3/3] Ejecutando las 6 pruebas académicas...")

    qwen_times = []
    mistral_times = []

    for tc in TEST_CASES:
        print("\n" + "=" * 85)
        print(f"📌 PRUEBA {tc['id']}: {tc['titulo']}")
        print(f"🎯 Postura Esperada: {tc['esperado']}")
        print("=" * 85)

        # Inferencia Qwen 1.5B Afinado
        prompt = ALPACA_PROMPT.format(SYSTEM_PROMPT, tc["entrada"])
        inputs = tokenizer([prompt], return_tensors="pt").to("cuda")

        t0_qwen = time.time()
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=100,
                temperature=0.1,
                pad_token_id=tokenizer.eos_token_id,
            )
        dur_qwen = time.time() - t0_qwen
        qwen_times.append(dur_qwen)

        decoded_qwen = tokenizer.decode(outputs[0], skip_special_tokens=True)
        resp_qwen = decoded_qwen.split("### Respuesta:")[-1].strip()

        # Inferencia Ministral 3B
        resp_mistral, dur_mistral = query_mistral_lm_studio(tc)
        mistral_times.append(dur_mistral)

        print(f"\n⚡ [Qwen 2.5 1.5B LoRA] (Tiempo: {dur_qwen:.2f}s | VRAM: ~1.2 GB):")
        print(f"   {resp_qwen}")

        print(f"\n🧠 [Ministral 3B (LM Studio)] (Tiempo: {dur_mistral:.2f}s | VRAM: ~3.8 GB):")
        print(f"   {resp_mistral}")

    print("\n\n" + "#" * 85)
    print("RESUMEN DE MÉTRICAS COMPARATIVAS")
    print("#" * 85)
    print(f"Velocidad promedio Qwen 1.5B Afinado: {sum(qwen_times)/len(qwen_times):.2f} s/cita")
    print(f"Velocidad promedio Ministral 3B:      {sum(mistral_times)/len(mistral_times):.2f} s/cita")
    print(f"Aceleración de Qwen 1.5B:             {(sum(mistral_times)/sum(qwen_times)):.2f}x más rápido")
    print("=" * 85)


if __name__ == "__main__":
    main()
