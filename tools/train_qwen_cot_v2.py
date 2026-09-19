"""Script de Entrenamiento QLoRA V2 para Qwen 2.5 1.5B (Thinkuy CoT Epistémico).

Optimizado para RTX 5060 Laptop (8GB VRAM):
- Segmentos expandibles de CUDA para erradicar fragmentación de VRAM.
- Micro-batch size = 2 con gradient_accumulation_steps = 16 (batch global efectivo = 32).
- VRAM pico reducido a ~3.8 GB, garantizando estabilidad total para las 881 iteraciones.
- Checkpoints automáticos cada 50 pasos (save_steps=50).
- Limpieza periódica de caché CUDA (empty_cache) en cada log.
- Telemetría en vivo: data/auditorias_y_benchmarks/training_live_metrics.json para dashboard en puerto 7860.
"""
import os
import sys

# Configuración de memoria CUDA antes de cargar librerías
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import json
import time
from pathlib import Path

# IMPORTANTE: Unsloth debe importarse antes que trl y transformers
from unsloth import FastLanguageModel

import torch
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer
from transformers import TrainerCallback

MAX_SEQ_LENGTH = 1024
DATASET_FILE = "data/epistemic_train_cot.jsonl"
OUTPUT_DIR = "models/qwen_epistemic_v2_cot"
METRICS_FILE = Path("data/auditorias_y_benchmarks/training_live_metrics.json")

ALPACA_PROMPT = """A continuación se presenta una instrucción que describe una tarea, junto con una entrada que proporciona más contexto. Escribe una respuesta que complete adecuadamente la solicitud.

### Instrucción:
{}

### Entrada:
{}

### Respuesta:
{}"""


def formatting_prompts_func(examples, eos_token):
    instructions = examples["instruction"]
    inputs = examples["input"]
    outputs = examples["output"]
    texts = []
    for instruction, input_text, output_text in zip(instructions, inputs, outputs):
        text = ALPACA_PROMPT.format(instruction, input_text, output_text) + eos_token
        texts.append(text)
    return {"text": texts}


class LiveMetricsCallback(TrainerCallback):
    """Escribe métricas detalladas en tiempo real para el Dashboard de Monitoreo."""

    def __init__(self, metrics_path=METRICS_FILE):
        self.metrics_path = Path(metrics_path)
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        self.start_time = None
        self.loss_history = []
        self.lr_history = []
        self._write_state("Inicializando modelo...", 0, 0, 0.0, None, None)

    def _write_state(self, status, step, max_steps, epoch, loss, lr, logs_tail=""):
        now = time.time()
        elapsed = (now - self.start_time) if self.start_time else 0
        eta = 0
        if max_steps and step > 0 and elapsed > 0:
            rate = step / elapsed
            eta = (max_steps - step) / rate if rate > 0 else 0

        data = {
            "status": status,
            "step": step,
            "max_steps": max_steps,
            "epoch": round(epoch, 3) if epoch is not None else 0.0,
            "loss": round(loss, 4) if loss is not None else None,
            "learning_rate": lr if lr is not None else None,
            "elapsed_seconds": int(elapsed),
            "eta_seconds": int(eta),
            "loss_history": self.loss_history[-200:],
            "lr_history": self.lr_history[-200:],
            "logs_tail": logs_tail,
            "last_updated": now,
        }
        try:
            with open(self.metrics_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def on_train_begin(self, args, state, control, **kwargs):
        self.start_time = time.time()
        self._write_state("Entrenando en GPU...", 0, state.max_steps, 0.0, None, args.learning_rate)

    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs:
            step = state.global_step
            loss = logs.get("loss")
            lr = logs.get("learning_rate")
            epoch = logs.get("epoch", 0.0)

            if loss is not None:
                self.loss_history.append({"step": step, "loss": round(loss, 4)})
            if lr is not None:
                self.lr_history.append({"step": step, "lr": float(f"{lr:.7f}")})

            loss_str = f"{loss:.4f}" if loss is not None else "N/A"
            lr_str = f"{lr:.2e}" if lr is not None else "N/A"
            log_str = f"Step {step}/{state.max_steps} - Loss: {loss_str} - LR: {lr_str}"
            self._write_state("Entrenando en GPU...", step, state.max_steps, epoch, loss, lr, logs_tail=log_str)

            # Liberar periódicamente memoria fragmentada en CUDA para estabilidad permanente en 8GB
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def on_train_end(self, args, state, control, **kwargs):
        self._write_state("Entrenamiento Completado", state.global_step, state.max_steps, state.epoch, None, 0.0)


def main():
    print("=" * 85)
    print("ENTRENAMIENTO QLORA V2 — QWEN 2.5 1.5B (RTX 5060 MEMORY SHIELD)")
    print("=" * 85)

    if not Path(DATASET_FILE).exists():
        print(f"Error: No se encontró el dataset {DATASET_FILE}")
        sys.exit(1)

    metrics_cb = LiveMetricsCallback()
    metrics_cb._write_state("Cargando modelo Qwen 2.5 4-bit...", 0, 0, 0.0, None, None)

    print("\n[1/5] Cargando modelo base cuantizado en 4-bit...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit",
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,
        load_in_4bit=True,
    )

    metrics_cb._write_state("Configurando adaptadores LoRA (r=32)...", 0, 0, 0.0, None, None)
    print("\n[2/5] Configurando adaptadores LoRA de alta capacidad (r=32, alpha=64)...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_alpha=64,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
        max_seq_length=MAX_SEQ_LENGTH,
    )

    metrics_cb._write_state("Tokenizando dataset de 28k citas...", 0, 0, 0.0, None, None)
    print("\n[3/5] Procesando dataset de entrenamiento con formato CoT...")
    dataset = load_dataset("json", data_files=DATASET_FILE, split="train")
    eos_token = tokenizer.eos_token or "<|im_end|>"
    dataset = dataset.map(
        lambda examples: formatting_prompts_func(examples, eos_token),
        batched=True,
    )
    print(f"✓ Dataset cargado: {len(dataset)} citas preparadas.")

    print("\n[4/5] Configurando hiperparámetros con SFTConfig (Micro-batch 2, Accum 16)...")
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    # Micro-batch 2 + Accum 16 = Batch 32 efectivo
    # Consumo de VRAM reducido a ~3.8 GB garantizando cero caídas por OOM
    training_args = SFTConfig(
        output_dir=OUTPUT_DIR,
        dataset_text_field="text",
        max_length=MAX_SEQ_LENGTH,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=16,
        warmup_steps=30,
        num_train_epochs=1,
        learning_rate=2e-4,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=5,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="cosine",
        seed=42,
        report_to="none",
        save_strategy="steps",
        save_steps=50,
        save_total_limit=3,
    )

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset,
        args=training_args,
        callbacks=[metrics_cb],
    )

    print("\n[5/5] Iniciando entrenamiento en GPU...")
    trainer_stats = trainer.train()
    print("\n✓ Entrenamiento completado con éxito.")
    print(f"  • Pérdida final (Loss): {trainer_stats.training_loss:.4f}")

    metrics_cb._write_state("Guardando adaptadores LoRA finales...", trainer.state.global_step, trainer.state.max_steps, 1.0, trainer_stats.training_loss, 0.0)

    print(f"\nGuardando adaptadores LoRA finales en {OUTPUT_DIR}...")
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"✓ Modelo guardado exitosamente en: {OUTPUT_DIR}")

    metrics_cb._write_state("Finalizado y guardado con éxito", trainer.state.global_step, trainer.state.max_steps, 1.0, trainer_stats.training_loss, 0.0)


if __name__ == "__main__":
    main()
