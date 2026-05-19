"""
embeddings.py — Generación de embeddings de texto con Ollama (local, sin costo)

CONCEPTO — Embeddings:
  Un embedding es una representación vectorial densa de un texto.
  "El módulo 3 trata sobre redes neuronales" y "¿qué vimos sobre redes?"
  producen vectores muy cercanos aunque no compartan palabras exactas.
  Esto permite búsqueda por SIGNIFICADO en lugar de coincidencia literal.

  Modelo usado: nomic-embed-text (Ollama)
    - Dimensión del vector: 768 números flotantes
    - Costo: GRATIS — corre completamente en tu máquina
    - Calidad: comparable a text-embedding-3-small de OpenAI para textos en español
    - Requisito: ollama pull nomic-embed-text

Diferencia clave OpenAI vs Ollama embeddings:
  OpenAI → llamada HTTP a api.openai.com → cobra por token → requiere internet
  Ollama → proceso local en tu CPU/GPU → gratis → funciona offline
"""

from functools import lru_cache
from langchain_ollama import OllamaEmbeddings
from app.config import get_settings


@lru_cache
def get_embedding_model() -> OllamaEmbeddings:
    """
    Retorna el modelo de embeddings local (Ollama).

    lru_cache garantiza que el objeto se crea una sola vez
    por proceso — no reconecta a Ollama en cada request.

    OllamaEmbeddings llama internamente a:
      POST http://localhost:11434/api/embeddings
      { "model": "nomic-embed-text", "prompt": "<texto>" }
    y retorna un vector de 768 dimensiones.
    """
    settings = get_settings()
    return OllamaEmbeddings(
        model=settings.ollama_embed_model,   # nomic-embed-text por defecto
        base_url=settings.ollama_base_url,
    )
