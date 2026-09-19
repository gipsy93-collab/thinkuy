"""Script de Comparación Tripartita:
1. Qwen 2.5 1.5B Base (Sin entrenar)
2. Modelo Fallido Anterior (LoRA 22 pasos / Underfitted)
3. Modelo Nuevo Exitoso (LoRA 190 pasos / 2 Épocas completas)
"""
import os
import sys
import json
import torch
from unsloth import FastLanguageModel

PATH_BASE = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"
PATH_FAILED_22 = r"C:\Users\gipsy\.unsloth\studio\outputs\unsloth_Qwen2.5-1.5B-Instruct-bnb-4bit__project-thinkuy-epistemic-qwen_1789428759"
PATH_SUCCESS_190 = r"C:\Users\gipsy\.unsloth\studio\outputs\unsloth_Qwen2.5-1.5B-Instruct-bnb-4bit__project-thinkuy-epistemic-qwen_1789479572"

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
        "titulo": "PRUEBA 1: DISENSO / REFUTACIÓN CONTUNDENTE",
        "entrada": "Contexto de citación: \"Sin embargo, a diferencia de los resultados reportados por Gómez et al. (2021), nuestros experimentos no encontraron una correlación estadísticamente significativa entre ambas variables.\"\nSección: Discusión",
        "esperado": "contrasting_or_refuting",
    },
    {
        "titulo": "PRUEBA 2: CONSENSO Y CONFIRMACIÓN EMPÍRICA",
        "entrada": "Contexto de citación: \"En concordancia con los hallazgos de Mendoza (2022), nuestros datos empíricos confirman de forma categórica la hipótesis de reducción del error basal.\"\nSección: Resultados",
        "esperado": "supporting_or_agreement",
    },
    {
        "titulo": "PRUEBA 3: ADOPCIÓN METODOLÓGICA",
        "entrada": "Contexto de citación: \"Para la recolección de los datos empíricos se adaptó el cuestionario de competencia digital docente desarrollado y validado por Cabero y Palacios (2020).\"\nSección: Metodología",
        "esperado": "methodological_adoption",
    },
    {
        "titulo": "PRUEBA 4: PÁRRAFO COMPLEJO TRIPARTITO",
        "entrada": "Contexto de citación: \"Si bien los trabajos de Silva (2019) sentaron las bases conceptuales, nuestros resultados contradicen abiertamente a Pérez (2020) al no hallar efectos protectores significativos.\"\nSección: Discusión",
        "esperado": "contrasting_or_refuting",
    },
]


def test_model(model_path, model_label):
    print(f"\n{'='*70}\nCARGANDO Y EVALUANDO: {model_label}\n{'='*70}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_path,
        max_seq_length=1024,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model)

    results = []
    for tc in TEST_CASES:
        prompt = ALPACA_PROMPT.format(SYSTEM_PROMPT, tc["entrada"])
        inputs = tokenizer([prompt], return_tensors="pt").to("cuda")
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=100,
                temperature=0.1,
                pad_token_id=tokenizer.eos_token_id,
            )
        decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)
        resp = decoded.split("### Respuesta:")[-1].strip()
        results.append((tc["titulo"], tc["esperado"], resp))

    # Liberar memoria
    del model
    del tokenizer
    torch.cuda.empty_cache()
    return results


def main():
    print("=" * 80)
    print("BENCHMARK COMPARATIVO TRIPARTITO (BASE vs FALLIDO vs NUEVO 190 PASOS)")
    print("=" * 80)

    res_failed = test_model(PATH_FAILED_22, "1. MODELO FALLIDO ANTERIOR (22 Pasos / Underfitted)")
    res_success = test_model(PATH_SUCCESS_190, "2. MODELO NUEVO EXITOSO (190 Pasos / 2 Épocas)")

    print("\n\n" + "#" * 80)
    print("CUADRO COMPARATIVO FINAL LADO A LADO")
    print("#" * 80)

    for i in range(len(TEST_CASES)):
        titulo, esp, out_fail = res_failed[i]
        _, _, out_succ = res_success[i]

        print(f"\n📌 {titulo}")
        print(f"🎯 Postura Esperada: {esp}")
        print(f"\n❌ [Modelo Fallido 22 Pasos]:")
        print(f"   {out_fail}")
        print(f"\n✅ [Modelo Nuevo 190 Pasos]:")
        print(f"   {out_succ}")
        print("-" * 70)


if __name__ == "__main__":
    main()
