"""
train.py — Script de fine-tuning del LLM

TODO: Implementar en FASE 4
Responsabilidad:
  - Tomar el dataset.jsonl con pares (prompt → completion)
  - Subir el dataset a OpenAI Fine-tuning API
  - Lanzar el job de entrenamiento con hiperparámetros configurables
  - Monitorear la loss curve hasta convergencia
  - Reportar el ID del modelo fine-tuneado para actualizar OPENAI_FINE_TUNED_MODEL en .env

HIPERPARÁMETROS configurables:
  - n_epochs: cuántas pasadas completas sobre el dataset (típico: 3-5)
  - learning_rate_multiplier: escala la tasa de aprendizaje base (típico: 0.1-2.0)
  - batch_size: ejemplos por paso de gradiente (auto o valor fijo)
"""

# Este módulo se implementa en FASE 4
