"""
train.py — Fine-tuning con LoRA/PEFT para Qwen3-4B

CONCEPTO — Por qué fine-tuning:
  Qwen3:4b es un modelo de propósito general. Fine-tuning lo adapta a:
  - Responder siempre en español conciso (estilo WhatsApp)
  - Priorizar el uso de tools MCP antes de inventar respuestas
  - Reconocer patrones de gestión académica ("agéndame", "¿qué tengo?")
  - Mantener el tono amigable y académico definido en el sistema

  Sin fine-tuning, se necesita un prompt largo y elaborado en cada request.
  Con fine-tuning, el comportamiento queda "horneado" en los pesos.

CONCEPTO — LoRA (Low-Rank Adaptation):
  En lugar de actualizar todos los parámetros del modelo (3.8B en Qwen3-4B),
  LoRA agrega matrices pequeñas de bajo rango a las capas de atención:

    W_actualizado = W_original + (A @ B) * scale
      donde A ∈ R^(d × r)  y  B ∈ R^(r × k)  con r << d,k

  Solo A y B se entrenan. Si r=16, reducimos los parámetros entrenables ~200x.
  El modelo original W_original queda congelado → no se "olvida" conocimiento.

HIPERPARÁMETROS CLAVE:
  --lora_r:      rango de las matrices LoRA (4-64, default 16)
                 Mayor r = más capacidad = más memoria = más riesgo de overfitting
  --lora_alpha:  escala de LoRA (típicamente 2×lora_r = 32)
                 Controla qué tanto "pesan" los adaptadores vs el modelo base
  --learning_rate: tasa de aprendizaje (1e-4 a 2e-4 para LoRA, mayor que full FT)
  --num_epochs:  pasadas sobre el dataset (3-5 para datasets pequeños)
  --batch_size:  ejemplos por paso de gradiente (4-16 según GPU disponible)
  --max_seq_len: longitud máxima de secuencia en tokens (512-2048)

USO:
  python train.py                          # con defaults
  python train.py --lora_r 8 --num_epochs 5 --learning_rate 2e-4

REQUISITOS:
  - GPU con ≥8GB VRAM (o usar CPU muy lento)
  - Modelo: Qwen/Qwen2.5-1.5B-Instruct (1.5B es suficiente para demostración)
    Nota: Qwen3-4B requiere ~16GB VRAM para entrenamiento con LoRA.
    Para demostración académica se recomienda Qwen2.5-1.5B-Instruct (~6GB VRAM).
  - pip install transformers peft trl accelerate datasets bitsandbytes

RESULTADO:
  El script guarda el adaptador LoRA en ./lora_adapter/
  Para usar con Ollama: convertir a GGUF con llama.cpp (ver instrucciones al final)
"""

import argparse
import json
import logging
import os
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, TaskType, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
)
from trl import SFTTrainer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Directorio base ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATASET_PATH = BASE_DIR / "dataset_full.jsonl"
OUTPUT_DIR = BASE_DIR / "lora_adapter"

# Modelo base recomendado para demostración académica (ajustable)
# Qwen2.5-1.5B-Instruct: ~6GB VRAM con LoRA (accesible con GPU consumer)
# Qwen/Qwen3-4B: ~16GB VRAM con LoRA (requiere RTX 3090/4090 o superior)
DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"


def parse_args() -> argparse.Namespace:
    """
    Define y parsea los hiperparámetros del entrenamiento.

    CONCEPTO — Hiperparámetros:
    Los hiperparámetros son decisiones de diseño que tomamos ANTES de entrenar.
    El modelo los necesita para configurarse, pero no los aprende del dataset.
    Los parámetros (pesos W) sí los aprende.
    """
    parser = argparse.ArgumentParser(description="Fine-tuning con LoRA para asistente académico")

    # ---- Modelo ----
    parser.add_argument("--model_name", type=str, default=DEFAULT_MODEL,
                        help="Modelo HuggingFace a fine-tunear")

    # ---- LoRA hiperparámetros ----
    parser.add_argument("--lora_r", type=int, default=16,
                        help="Rango de las matrices LoRA (4-64)")
    parser.add_argument("--lora_alpha", type=int, default=32,
                        help="Factor de escala LoRA (típicamente 2×lora_r)")
    parser.add_argument("--lora_dropout", type=float, default=0.05,
                        help="Dropout en los adaptadores LoRA")

    # ---- Entrenamiento hiperparámetros ----
    parser.add_argument("--learning_rate", type=float, default=2e-4,
                        help="Tasa de aprendizaje")
    parser.add_argument("--num_epochs", type=int, default=3,
                        help="Número de epochs de entrenamiento")
    parser.add_argument("--batch_size", type=int, default=4,
                        help="Batch size por dispositivo")
    parser.add_argument("--max_seq_len", type=int, default=512,
                        help="Longitud máxima de secuencia en tokens")
    parser.add_argument("--warmup_ratio", type=float, default=0.1,
                        help="Fracción de steps para warm-up del LR")
    parser.add_argument("--grad_accumulation", type=int, default=4,
                        help="Pasos de acumulación de gradiente (batch efectivo = batch×grad)")

    # ---- Dataset ----
    parser.add_argument("--dataset_path", type=str, default=str(DATASET_PATH),
                        help="Ruta al archivo JSONL de entrenamiento")

    # ---- Salida ----
    parser.add_argument("--output_dir", type=str, default=str(OUTPUT_DIR),
                        help="Directorio donde guardar el adaptador LoRA")

    return parser.parse_args()


def load_dataset_from_jsonl(path: str) -> Dataset:
    """
    Carga el dataset desde un archivo JSONL con formato chat.

    Formato esperado (ChatML):
    {"messages": [
        {"role": "system", "content": "..."},
        {"role": "user",   "content": "..."},
        {"role": "assistant", "content": "..."}
    ]}

    El SFTTrainer de TRL espera una columna 'text' con el formato del template
    del modelo, o una columna 'messages' para templates de chat automáticos.
    """
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    logger.info(f"Dataset cargado: {len(records)} ejemplos desde {path}")
    return Dataset.from_list(records)


def apply_chat_template(examples: dict, tokenizer) -> dict:
    """
    Convierte los mensajes al formato de texto que espera el modelo.

    Cada modelo tiene su propio template de chat. Para Qwen2.5:
      <|im_start|>system\n{system}<|im_end|>\n
      <|im_start|>user\n{user}<|im_end|>\n
      <|im_start|>assistant\n{assistant}<|im_end|>

    tokenizer.apply_chat_template() aplica el template correcto automáticamente.
    """
    texts = []
    for messages in examples["messages"]:
        text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False,
        )
        texts.append(text)
    return {"text": texts}


def build_lora_config(args: argparse.Namespace) -> LoraConfig:
    """
    Construye la configuración LoRA.

    target_modules: capas donde aplicar los adaptadores.
    Para Qwen2.5/Qwen3, las capas de atención son q_proj, k_proj, v_proj, o_proj.
    Agregar gate_proj, up_proj, down_proj (FFN) mejora la capacidad pero usa más memoria.

    CONCEPTO — task_type=CAUSAL_LM:
    Indica que es un modelo de lenguaje causal (predice el siguiente token).
    Esto es diferente de SEQUENCE_CLASSIFICATION o SEQ_2_SEQ_LM.
    """
    return LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        # Capas target para Qwen2.5/Qwen3
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        # inference_mode=False para entrenamiento
        inference_mode=False,
    )


def main():
    args = parse_args()

    logger.info("=" * 60)
    logger.info("FINE-TUNING CON LoRA — ASISTENTE ACADÉMICO")
    logger.info("=" * 60)
    logger.info(f"Modelo base:    {args.model_name}")
    logger.info(f"LoRA r={args.lora_r}, alpha={args.lora_alpha}, dropout={args.lora_dropout}")
    logger.info(f"LR={args.learning_rate}, epochs={args.num_epochs}, batch={args.batch_size}")
    logger.info(f"Dataset:        {args.dataset_path}")
    logger.info(f"Salida:         {args.output_dir}")

    # ── 1. Cargar tokenizer ──────────────────────────────────────────────────
    logger.info("\n[1/5] Cargando tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_name,
        trust_remote_code=True,
        padding_side="right",  # padding a la derecha para entrenamiento causal
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # ── 2. Cargar modelo base ────────────────────────────────────────────────
    logger.info("[2/5] Cargando modelo base...")
    logger.info("  (Esto puede tardar varios minutos en la primera descarga)")

    # torch_dtype=float16 reduce el uso de VRAM ~50% vs float32
    # device_map="auto" distribuye las capas automáticamente (CPU+GPU si es necesario)
    model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )

    # Deshabilitar cache para entrenamiento (incompatible con gradient checkpointing)
    model.config.use_cache = False
    model.config.pretraining_tp = 1

    # ── 3. Aplicar LoRA al modelo ────────────────────────────────────────────
    logger.info("[3/5] Aplicando adaptadores LoRA...")
    lora_config = build_lora_config(args)
    model = get_peft_model(model, lora_config)

    # Reportar parámetros entrenables vs totales
    trainable, total = 0, 0
    for _, param in model.named_parameters():
        total += param.numel()
        if param.requires_grad:
            trainable += param.numel()
    pct = 100 * trainable / total
    logger.info(f"  Parámetros totales:     {total:,}")
    logger.info(f"  Parámetros entrenables: {trainable:,} ({pct:.2f}%)")

    # ── 4. Preparar dataset ──────────────────────────────────────────────────
    logger.info("[4/5] Preparando dataset...")
    raw_dataset = load_dataset_from_jsonl(args.dataset_path)

    # Aplicar template de chat del modelo
    dataset = raw_dataset.map(
        lambda examples: apply_chat_template(examples, tokenizer),
        batched=True,
        remove_columns=raw_dataset.column_names,
    )

    # Split 90% train / 10% evaluación
    split = dataset.train_test_split(test_size=0.1, seed=42)
    train_dataset = split["train"]
    eval_dataset = split["test"]
    logger.info(f"  Train: {len(train_dataset)} ejemplos | Eval: {len(eval_dataset)} ejemplos")

    # ── 5. Configurar y lanzar entrenamiento ─────────────────────────────────
    logger.info("[5/5] Iniciando entrenamiento...")

    # CONCEPTO — TrainingArguments:
    # Configuración completa del loop de entrenamiento.
    # gradient_accumulation_steps: simula un batch más grande acumulando gradientes
    # antes de hacer el step del optimizador. batch_efectivo = batch × grad_accum
    training_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.num_epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accumulation,
        learning_rate=args.learning_rate,
        warmup_ratio=args.warmup_ratio,
        # Scheduler: cosine decay — el LR decrece suavemente hasta 0
        lr_scheduler_type="cosine",
        # Optimizador: paged_adamw_8bit ahorra memoria en GPU
        # Si no hay bitsandbytes, cambia a "adamw_torch"
        optim="paged_adamw_8bit",
        fp16=True,                          # entrenamiento en float16
        eval_strategy="epoch",              # evaluar al final de cada epoch
        save_strategy="epoch",              # guardar checkpoint cada epoch
        load_best_model_at_end=True,        # cargar el mejor checkpoint al final
        logging_steps=10,                   # log de pérdida cada N steps
        report_to="none",                   # desactivar wandb/tensorboard
        dataloader_pin_memory=False,
    )

    # SFTTrainer (Supervised Fine-Tuning Trainer) de TRL
    # Maneja el formateo del dataset, el masking de tokens del sistema/usuario
    # (solo calculamos pérdida sobre los tokens del asistente) y el training loop.
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        dataset_text_field="text",
        max_seq_length=args.max_seq_len,
        packing=False,                      # no empaquetar múltiples ejemplos por secuencia
    )

    # ── ENTRENAMIENTO ────────────────────────────────────────────────────────
    logger.info("\n🚀 Iniciando entrenamiento LoRA...")
    logger.info(f"   Steps por epoch: {len(train_dataset) // (args.batch_size * args.grad_accumulation)}")
    logger.info(f"   Total steps: ~{args.num_epochs * len(train_dataset) // (args.batch_size * args.grad_accumulation)}")

    train_result = trainer.train()

    # ── GUARDAR ADAPTADOR ────────────────────────────────────────────────────
    logger.info("\n💾 Guardando adaptador LoRA...")
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    logger.info(f"\n✅ Entrenamiento completado!")
    logger.info(f"   Pérdida final: {train_result.training_loss:.4f}")
    logger.info(f"   Adaptador guardado en: {args.output_dir}")

    # ── INSTRUCCIONES POST-ENTRENAMIENTO ─────────────────────────────────────
    logger.info("""
╔══════════════════════════════════════════════════════════════════╗
║           SIGUIENTES PASOS PARA USAR CON OLLAMA                  ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  1. MERGE: combinar adaptador con modelo base                    ║
║     from peft import PeftModel                                   ║
║     base = AutoModelForCausalLM.from_pretrained(BASE_MODEL)      ║
║     merged = PeftModel.from_pretrained(base, LORA_DIR)           ║
║     merged = merged.merge_and_unload()                           ║
║     merged.save_pretrained("./merged_model")                     ║
║                                                                  ║
║  2. CONVERTIR a GGUF (requiere llama.cpp):                       ║
║     python llama.cpp/convert.py ./merged_model --outfile q3.gguf ║
║     llama.cpp/quantize q3.gguf q3-q4_k_m.gguf Q4_K_M            ║
║                                                                  ║
║  3. CREAR Modelfile para Ollama:                                  ║
║     FROM ./q3-q4_k_m.gguf                                        ║
║     SYSTEM "Eres un asistente académico..."                      ║
║                                                                  ║
║  4. REGISTRAR en Ollama:                                         ║
║     ollama create asistente-academico -f Modelfile               ║
║     ollama run asistente-academico                               ║
║                                                                  ║
║  5. ACTUALIZAR .env:                                             ║
║     OLLAMA_MODEL=asistente-academico                             ║
╚══════════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()

