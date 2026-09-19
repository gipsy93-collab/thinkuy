"""Script de Exportación a GGUF (Q4_K_M) del Modelo Epistémico Qwen 2.5 1.5B Afinado.

Fusiona los adaptadores LoRA entrenados (Paso 190 / Época 2.0) y genera el archivo .gguf
listo para cargar directamente en LM Studio, Ollama o Thinkuy.
"""
import os
import sys
from pathlib import Path
import torch
from unsloth import FastLanguageModel

# Rutas
LORA_PATH = r"C:\Users\gipsy\.unsloth\studio\outputs\unsloth_Qwen2.5-1.5B-Instruct-bnb-4bit__project-thinkuy-epistemic-qwen_1789479572"
GGUF_OUTPUT_DIR = "exports/thinkuy_qwen25_1_5b_gguf"
MAX_SEQ_LENGTH = 1024

print("=" * 80)
print("EXPORTACIÓN A FORMATO GGUF (Q4_K_M) — THINKUY EPISTEMIC QWEN 2.5 1.5B")
print("=" * 80)
print(f"Directorio de adaptadores LoRA: {LORA_PATH}")
print(f"Directorio de destino GGUF:      {GGUF_OUTPUT_DIR}")

if not Path(LORA_PATH).exists():
    print(f"[ERROR] No se encontró la carpeta de adaptadores en: {LORA_PATH}")
    sys.exit(1)

print("\n[1/2] Cargando modelo base y fusionando adaptadores LoRA...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=LORA_PATH,
    max_seq_length=MAX_SEQ_LENGTH,
    dtype=None,
    load_in_4bit=True,
)

# Activar modo de inferencia rápida
FastLanguageModel.for_inference(model)

print(f"\n[2/2] Compilando y cuantizando a GGUF (q4_k_m)...")
Path(GGUF_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

model.save_pretrained_gguf(
    GGUF_OUTPUT_DIR,
    tokenizer,
    quantization_method="q4_k_m",
)

print("\n" + "=" * 80)
print("¡EXPORTACIÓN COMPLETADA CON ÉXITO!")
print(f"Archivo GGUF generado en: {GGUF_OUTPUT_DIR}/")
print("Listo para arrastrar y soltar en LM Studio o usar directamente en Thinkuy.")
print("=" * 80)
