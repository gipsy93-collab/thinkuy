"""Script de Entrenamiento Thinkuy V3 (QLoRA con Unsloth).
Soporta modo --dry-run (5 pasos) para validación previa de VRAM y gradientes.
"""
import os
import sys
import argparse
import torch

# Unsloth debe importarse antes de transformers y peft
from unsloth import FastLanguageModel
from unsloth import is_bfloat16_supported
import unsloth_zoo.fused_losses.cross_entropy_loss as ce_loss_mod
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments

# Parche de seguridad para GPUs de 8GB con modelos de vocabulario masivo (Gemma 4: 256k vocab)
def safe_get_chunk_multiplier(vocab_size, target_gb=None, fixed_gb=0.0):
    try:
        free, total = torch.cuda.mem_get_info(0)
        free_gb = max((free / (1024**3)) * 0.5, 0.25)
    except Exception:
        free_gb = 0.5
    target_gb = min(free_gb, 4.0)
    if 0.0 < fixed_gb < target_gb:
        target_gb = target_gb - fixed_gb
    multiplier = (vocab_size * ce_loss_mod._CE_BYTES_PER_LOGIT / 1024 / 1024 / 1024) / target_gb
    return multiplier / 4

ce_loss_mod._get_chunk_multiplier = safe_get_chunk_multiplier


def main():
    parser = argparse.ArgumentParser(description="Entrenamiento Thinkuy V3 con Unsloth")
    parser.add_argument("--dry-run", action="store_true", help="Ejecuta solo 5 pasos de prueba para validar VRAM y gradientes")
    parser.add_argument("--model-name", type=str, default="unsloth/gemma-4-E2B-it-unsloth-bnb-4bit", help="Modelo base en HuggingFace")
    parser.add_argument("--max-seq-length", type=int, default=512, help="Longitud máxima de contexto")
    parser.add_argument("--epochs", type=int, default=3, help="Número de épocas completas")
    parser.add_argument("--batch-size", type=int, default=1, help="Batch size por dispositivo")
    parser.add_argument("--grad-accum", type=int, default=4, help="Gradient accumulation steps")
    parser.add_argument("--learning-rate", type=float, default=2e-4, help="Tasa de aprendizaje")
    parser.add_argument("--output-dir", type=str, default="models/thinkuy_v3_gemma4_lora", help="Directorio de salida para adaptadores LoRA")
    args = parser.parse_args()

    print("=" * 70)
    print("THINKUY V3 — MOTOR DE ENTRENAMIENTO GEMMA 4 E2B (UNSLOTH)")
    print(f"Modo: {'DRY RUN (Simulación 5 pasos)' if args.dry_run else 'ENTRENAMIENTO COMPLETO'}")
    print(f"Modelo base: {args.model_name}")
    print(f"GPU detectada: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No GPU'}")
    print(f"VRAM inicial: {torch.cuda.memory_allocated(0)/1024**3:.2f} GB / {torch.cuda.get_device_properties(0).total_memory/1024**3:.2f} GB")
    print("=" * 70)

    # 1. Cargar Modelo y Tokenizer con Unsloth (4-bit cuantización en GPU 0)
    print("\n[1/4] Cargando Gemma 4 E2B y cuantización 4-bit...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model_name,
        max_seq_length=args.max_seq_length,
        load_in_4bit=True,
        device_map={"": 0},
        dtype=None,  # Auto detección (bfloat16)
    )

    # 2. Configurar Adaptadores PEFT (LoRA) para lenguaje
    print("\n[2/4] Inyectando adaptadores LoRA (modo lenguaje)...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        finetune_vision_layers=False,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    # 3. Preparar Dataset ChatML
    dataset_path = "data/thinkuy_v3_gold_standard_chatml.jsonl"
    print(f"\n[3/4] Cargando dataset desde {dataset_path}...")
    dataset = load_dataset("json", data_files=dataset_path, split="train")
    print(f"Total ejemplos en dataset: {len(dataset)}")

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
        output_dir="scratch/dry_run_output" if args.dry_run else args.output_dir,
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

    print(f"\n[4/4] Iniciando {'Dry Run (5 pasos)' if args.dry_run else 'Entrenamiento'}...")
    print(f"VRAM antes de train: {torch.cuda.memory_allocated(0)/1024**3:.2f} GB")
    
    trainer_stats = trainer.train()

    print("\n" + "=" * 70)
    print(f"RESULTADO {'DRY RUN' if args.dry_run else 'ENTRENAMIENTO'}: EXITOSO")
    print(f"Pérdida final (Loss): {trainer_stats.training_loss:.4f}")
    print(f"Tiempo total: {trainer_stats.metrics['train_runtime']:.2f} segundos")
    print(f"VRAM pico utilizada: {torch.cuda.max_memory_allocated(0)/1024**3:.2f} GB")
    print("=" * 70)

    if not args.dry_run:
        print(f"\nGuardando adaptadores LoRA en {args.output_dir}...")
        os.makedirs(args.output_dir, exist_ok=True)
        model.save_pretrained(args.output_dir)
        tokenizer.save_pretrained(args.output_dir)
        print("Modelo guardado correctamente.")

if __name__ == "__main__":
    main()
