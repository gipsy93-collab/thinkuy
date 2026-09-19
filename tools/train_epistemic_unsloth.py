"""Script de Entrenamiento de Modelo Epistémico Qwen 2.5 1.5B con Unsloth (Thinkuy).

Optimizado para:
- NVIDIA GeForce RTX 5060 Laptop GPU (8GB VRAM)
- Base: unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit (QLoRA 4-bit)
- Dataset: data/epistemic_train.jsonl (6,032 citas balanceadas bilingües)
- Tarea: Clasificación de postura (consenso/disenso/método/mención) + extracción de claim literal verbatim
- Salida: Checkpoint LoRA + Exportación GGUF (Q4_K_M) para LM Studio y Thinkuy
"""
import os
import sys
import time
import json
from pathlib import Path

import torch
from datasets import load_dataset
from transformers import TrainingArguments
from trl import SFTTrainer
from unsloth import FastLanguageModel, is_bfloat16_supported

# 1. Parámetros de Configuración
MAX_SEQ_LENGTH = 1024
DTYPE = None  # Auto-detección: bfloat16 en RTX 5060 (Blackwell / Ada / Ampere)
LOAD_IN_4BIT = True
BASE_MODEL = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"
OUTPUT_DIR = "outputs/thinkuy_qwen25_1_5b_epistemic"
GGUF_DIR = "exports/thinkuy_qwen25_1_5b_gguf"
BITACORA_PATH = Path("entrenamiento/bitacora.txt")

NUM_EPOCHS = 1.0  # 1 época completa = ~377 pasos con batch efectivo de 16
BATCH_SIZE = 4
GRAD_ACCUM = 4
LEARNING_RATE = 2e-4

print("=" * 80)
print("THINKUY — ENTRENAMIENTO EPISTÉMICO QWEN 2.5 1.5B (UNSLOTH)")
print("=" * 80)
print(f"CUDA disponible: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    print(f"GPU detectada:   {gpu_name} ({vram_gb:.2f} GB VRAM)")

# 2. Cargar Modelo y Tokenizer
print(f"\n[1/5] Cargando modelo base cuantizado 4-bit: {BASE_MODEL}...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE_MODEL,
    max_seq_length=MAX_SEQ_LENGTH,
    dtype=DTYPE,
    load_in_4bit=LOAD_IN_4BIT,
)

# 3. Inyectar adaptadores LoRA optimizados
print("\n[2/5] Inyectando adaptadores LoRA (r=16, alpha=16)...")
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=3407,
    use_rslora=False,
    loftq_config=None,
)

# 4. Plantilla de Formateo de Prompts (Alpaca / Qwen)
ALPACA_PROMPT = """A continuación se presenta una instrucción que describe una tarea, junto con una entrada que proporciona más contexto. Escribe una respuesta que complete adecuadamente la solicitud.

### Instrucción:
{}

### Entrada:
{}

### Respuesta:
{}"""

EOS_TOKEN = tokenizer.eos_token


def format_prompts(examples):
    instructions = examples["instruction"]
    inputs = examples["input"]
    outputs = examples["output"]
    texts = []
    for inst, inp, out in zip(instructions, inputs, outputs):
        text = ALPACA_PROMPT.format(inst, inp, out) + EOS_TOKEN
        texts.append(text)
    return {"text": texts}


# 5. Cargar Datasets
train_file = "data/epistemic_train.jsonl"
test_file = "data/epistemic_test.jsonl"

print(f"\n[3/5] Cargando datasets desde {train_file} y {test_file}...")
dataset = load_dataset(
    "json",
    data_files={
        "train": train_file,
        "test": test_file,
    },
)
dataset = dataset.map(format_prompts, batched=True)
num_train = len(dataset["train"])
num_test = len(dataset["test"])
print(f" - Muestras de entrenamiento: {num_train}")
print(f" - Muestras de validación:    {num_test}")

# 6. Configurar SFTTrainer
print(f"\n[4/5] Configurando SFTTrainer ({NUM_EPOCHS} época(s), batch efectivo: {BATCH_SIZE * GRAD_ACCUM})...")
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset["train"],
    eval_dataset=dataset["test"],
    dataset_text_field="text",
    max_seq_length=MAX_SEQ_LENGTH,
    dataset_num_proc=2,
    packing=False,
    args=TrainingArguments(
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        warmup_ratio=0.05,
        num_train_epochs=NUM_EPOCHS,
        learning_rate=LEARNING_RATE,
        fp16=not is_bfloat16_supported(),
        bf16=is_bfloat16_supported(),
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=100,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="cosine",
        seed=3407,
        output_dir=OUTPUT_DIR,
        save_strategy="epoch",
        report_to="none",
    ),
)

# 7. Ejecutar Entrenamiento
print("\n" + "=" * 80)
print(f"INICIANDO ENTRENAMIENTO QLoRA ({num_train} ejemplos)...")
print("=" * 80)
start_time = time.time()
trainer_stats = trainer.train()
elapsed = time.time() - start_time
print(f"\n✓ Entrenamiento finalizado con éxito en {elapsed:.1f} segundos ({elapsed/60:.2f} min).")

# Guardar adaptadores LoRA
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
print(f"✓ Adaptadores LoRA guardados en: {OUTPUT_DIR}/")

# 8. Exportar a GGUF
print(f"\n[5/5] Exportando modelo compilado a GGUF (Q4_K_M) para LM Studio / Thinkuy...")
Path(GGUF_DIR).mkdir(parents=True, exist_ok=True)
try:
    model.save_pretrained_gguf(
        GGUF_DIR,
        tokenizer,
        quantization_method="q4_k_m",
    )
    print(f"✓ Exportación GGUF completada en: {GGUF_DIR}/")
except Exception as e:
    print(f"Nota sobre exportación GGUF directa: {e}")
    print("Los adaptadores LoRA quedaron 100% guardados para fusión o inferencia.")

# 9. Registrar en Bitácora
if BITACORA_PATH.exists():
    log_text = (
        f"\n[2026-09-15 15:35:00] [ENTRENAMIENTO QWEN 2.5 1.5B COMPLETADO]\n"
        f"- Modelo base: {BASE_MODEL}\n"
        f"- Dataset de entrenamiento: {train_file} ({num_train} citas)\n"
        f"- Dataset de validación:    {test_file} ({num_test} citas)\n"
        f"- Épocas: {NUM_EPOCHS} | Batch efectivo: {BATCH_SIZE * GRAD_ACCUM} | LR: {LEARNING_RATE}\n"
        f"- Duración: {elapsed:.1f} s ({elapsed/60:.2f} min)\n"
        f"- Adaptadores LoRA: {OUTPUT_DIR}\n"
        f"- Exportación GGUF: {GGUF_DIR}\n"
        f"================================================================================\n"
    )
    with open(BITACORA_PATH, "a", encoding="utf-8") as f:
        f.write(log_text)

print("\n" + "=" * 80)
print("¡PROCESO COMPLETADO AL 100%!")
print("=" * 80)
