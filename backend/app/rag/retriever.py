"""
retriever.py — Búsqueda semántica (top-k) en la BD vectorial

CONCEPTO RAG — Retrieval:
  El retriever convierte la pregunta del usuario en un vector y busca los
  k documentos más "cercanos" en el espacio vectorial usando similitud coseno.

  Similitud coseno = cos(θ) entre dos vectores A y B:
    cos(θ) = (A · B) / (|A| × |B|)
  Valor 1 → vectores idénticos (mismo significado)
  Valor 0 → vectores ortogonales (significados no relacionados)

  El resultado es una lista de fragmentos de texto ordenados por relevancia.
  Estos fragmentos se inyectan en el prompt del LLM como contexto.

FLUJO:
  Pregunta del usuario (str)
    → embedding del query (vector 1536-dim)
    → búsqueda en Chroma (similitud coseno contra todos los vectores)
    → top-k documentos más cercanos
    → texto concatenado como contexto para el LLM
"""

import logging
from langchain_community.vectorstores import Chroma

from app.rag.ingestion import get_vector_store

logger = logging.getLogger(__name__)

TOP_K = 3  # número de fragmentos a recuperar por búsqueda


def retrieve_context(query: str, k: int = TOP_K) -> str:
    """
    Busca los k fragmentos más relevantes para el query dado.

    Args:
        query: pregunta o texto del usuario
        k: número de fragmentos a recuperar (top-k)

    Returns:
        Texto concatenado de los k fragmentos más relevantes,
        listo para inyectar en el system prompt del LLM.
        Si no hay documentos indexados, retorna string vacío.

    NOTA ACADÉMICA — ¿Por qué top-k y no todos?
        Inyectar todos los fragmentos en el prompt:
          1. Excede el context window del LLM
          2. Añade ruido: información irrelevante confunde al modelo
          3. Aumenta el costo (más tokens = más $)
        Con k=3 recuperamos lo suficiente sin saturar el contexto.
        En FASE 5 agregaremos un re-ranker para mejorar la precisión.
    """
    vector_store: Chroma = get_vector_store()

    # Verificamos que haya documentos indexados antes de buscar
    if vector_store._collection.count() == 0:
        logger.warning("La BD vectorial está vacía. Ejecuta el script de ingestión primero.")
        return ""

    # similarity_search devuelve Document objects con .page_content y .metadata
    docs = vector_store.similarity_search(query, k=k)

    if not docs:
        return ""

    # Formateamos el contexto indicando la fuente de cada fragmento
    # para que el LLM pueda citar de dónde viene la información.
    context_parts = []
    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source_file", "desconocido")
        context_parts.append(f"[Fragmento {i} — fuente: {source}]\n{doc.page_content}")

    context = "\n\n---\n\n".join(context_parts)
    logger.info(f"Recuperados {len(docs)} fragmentos para el query: {query!r}")
    return context
