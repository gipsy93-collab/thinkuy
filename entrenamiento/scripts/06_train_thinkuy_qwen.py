"""
=============================================================================
Thinkuy V3 — Entrenamiento LoRA Supervisado para Qwen 2.5 1.5B (Unsloth)
=============================================================================
Entrena el modelo compacto Qwen 2.5 1.5B con LoRA (4-bit) sobre el dataset
Gold Standard ChatML de Thinkuy (Micro-tareas: T1 Screening, T2 PCC, T3 Citas).
Aplica 'train_on_responses_only' para fijar taxativamente la salida <pensamiento>
y <salida_json> sin degradar la comprensión del texto científico.
=============================================================================
"""

import os
import sys
import argparse
import torch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template, train_on_responses_only
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments

def main():
    parser = argparse.ArgumentParser(description="Entrenamiento Thinkuy Qwen 2.5 1.5B LoRA")
    parser.add_argument("--dry-run", action="store_true", help="Ejecuta solo 5 pasos de prueba para validar VRAM y gradientes")
    parser.add_argument("--model-name", type=str, default="unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit", help="Modelo base en HuggingFace")
    parser.add_argument("--max-seq-length", type=int, default=1536, help="Longitud máxima de contexto para micro-fragmentos")
    parser.add_argument("--epochs", type=int, default=3, help="Número de épocas completas")
    parser.add_argument("--batch-size", type=int, default=2, help="Batch size por dispositivo")
    parser.add_argument("--grad-accum", type=int, default=4, help="Gradient accumulation steps")
    parser.add_argument("--learning-rate", type=float, default=2e-4, help="Tasa de aprendizaje")
    parser.add_argument("--output-dir", type=str, default="models/thinkuy_v3_qwen1.5b_lora", help="Directorio de salida para adaptadores LoRA")
    parser.add_argument("--dataset-path", type=str, default="data/thinkuy_v3_gold_standard_chatml.jsonl", help="Ruta al dataset de entrenamiento ChatML")
    args = parser.parse_args()

    print("=" * 80)
    print("THINKUY V3 — MOTOR DE ENTRENAMIENTO QWEN 2.5 1.5B (UNSLOTH LoRA)")
    print(f"Modo: {'DRY RUN (Simulación 5 pasos)' if args.dry_run else 'ENTRENAMIENTO COMPLETO'}")
    print(f"Modelo base: {args.model_name}")
    print(f"GPU detectada: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No GPU'}")
    print(f"VRAM inicial: {torch.cuda.memory_allocated(0)/1024**3:.2f} GB / {torch.cuda.get_device_properties(0).total_memory/1024**3:.2f} GB")
    print("=" * 80)

    # 1. Cargar Modelo y Tokenizer
    print("\n[1/4] Cargando Qwen 2.5 1.5B (4-bit)...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model_name,
        max_seq_length=args.max_seq_length,
        load_in_4bit=True,
        device_map={"": 0},
        dtype=None, # Auto bfloat16
    )

    # 2. Configurar Adaptadores PEFT LoRA
    print("\n[2/4] Inyectando adaptadores LoRA en capas de atención y MLP...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    # 3. Preparar Dataset ChatML
    print(f"\n[3/4] Cargando dataset desde {args.dataset_path}...")
    dataset = load_dataset("json", data_files=args.dataset_path, split="train")
    print(f"Total ejemplos en dataset: {len(dataset)}")

    tokenizer = get_chat_template(
        tokenizer,
        chat_template="chatml",
    )

    def formatting_prompts_func(examples):
        convos = examples["messages"]
        texts = [tokenizer.apply_chat_template(convo, tokenize=False, add_generation_prompt=False) for convo in convos]
        return {"text": texts}

    dataset = dataset.map(formatting_prompts_func, batched=True)

    # 4. Configurar Trainer
    max_steps = 5 if args.dry_run else -1
    num_train_epochs = 1 if args.dry_run else args.epochs
    logging_steps = 1 if args.dry_run else 5

    training_args = TrainingArguments(
        output_dir="scratch/dry_run_qwen" if args.dry_run else args.output_dir,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        warmup_steps=1 if args.dry_run else 5,
        max_steps=max_steps,
        num_train_epochs=num_train_epochs,
        learning_rate=args.learning_rate,
        fp16=False,
        bf16=True,
        logging_steps=logging_steps,
        optim="paged_adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=3407,
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=args.max_seq_length,
        dataset_num_proc=1,
        packing=False,
        args=training_args,
    )

    # Enmascarar pérdida: solo calcular gradientes en la respuesta del asistente
    trainer = train_on_responses_only(
        trainer,
        instruction_part="<|im_start|>user\n",
        response_part="<|im_start|>assistant\n",
    )

    print(f"\n[4/4] Iniciando {'Dry Run (5 pasos)' if args.dry_run else f'Entrenamiento ({args.epochs} épocas)'}...")
    print(f"VRAM antes de train: {torch.cuda.memory_allocated(0)/1024**3:.2f} GB")
    
    trainer_stats = trainer.train()

    print("\n" + "=" * 80)
    print(f"RESULTADO {'DRY RUN' if args.dry_run else 'ENTRENAMIENTO'}: EXITOSO")
    print(f"Pérdida final (Loss): {trainer_stats.training_loss:.4f}")
    print(f"Tiempo total: {trainer_stats.metrics['train_runtime']:.2f} segundos")
    print(f"VRAM pico utilizada: {torch.cuda.max_memory_allocated(0)/1024**3:.2f} GB")
    print("=" * 80)

    if not args.dry_run:
        print(f"\nGuardando adaptadores LoRA en {args.output_dir}...")
        os.makedirs(args.output_dir, exist_ok=True)
        model.save_pretrained(args.output_dir)
        tokenizer.save_pretrained(args.output_dir)
        print(f"[OK] Adaptadores LoRA guardados exitosamente en: {args.output_dir}")

if __name__ == "__main__":
    main()
