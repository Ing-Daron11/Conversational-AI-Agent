"""
reranker.py — Re-ranker de dos etapas para RAG avanzado

CONCEPTO — El problema del retriever básico:
  En FASE 1 usamos un bi-encoder para el retrieval:
    - El texto se convierte a un vector (nomic-embed-text)
    - Búsqueda por similitud coseno entre vectores

  Problema: el bi-encoder codifica query y documentos POR SEPARADO.
  No puede capturar la interacción semántica fina entre ambos.
  Ejemplo: "banco en el parque" vs "banco financiero" pueden tener
  vectores muy cercanos si el contexto no es suficientemente discriminante.

CONCEPTO — Cross-encoder (re-ranker):
  Un cross-encoder recibe el par (query, documento) CONCATENADOS y
  calcula directamente un score de relevancia:

    input:  "[CLS] ¿qué es backprop? [SEP] El algoritmo backpropagation..."
    output: score de relevancia ∈ (-∞, +∞)

  Puede capturar la interacción entre query y documento.
  Es mucho más preciso que el bi-encoder, pero también más lento
  porque no se puede pre-calcular el embedding del documento.

PIPELINE DE DOS ETAPAS (estándar en producción RAG):
  1. RETRIEVAL rápido con bi-encoder → recuperar k=15 candidatos
     (ChromaDB / Pinecone → similitud coseno → fast, approximate)

  2. RE-RANKING preciso con cross-encoder → quedarnos con top n=3
     (CrossEncoder.predict([(query, doc1), (query, doc2), ...]) → scores exactos)

  Resultado: precisión mucho mayor con latencia aceptable.
  El cross-encoder solo evalúa 15 pares, no todos los documentos.

MODELO USADO:
  cross-encoder/ms-marco-MiniLM-L-6-v2
  - Tamaño: ~66MB (descarga automática en primer uso)
  - Latencia: ~10ms para 15 pares en CPU
  - Entrenado en MS MARCO (dataset de preguntas-respuestas de Bing)
  - Alternativa más precisa: cross-encoder/ms-marco-electra-base (~440MB)
"""

import logging
from functools import lru_cache
from typing import List

from langchain.schema import Document

logger = logging.getLogger(__name__)

# Modelo de cross-encoder pre-entrenado
# Cambia a "cross-encoder/ms-marco-electra-base" para mayor precisión (~8x más lento)
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Cantidad de candidatos a recuperar ANTES de re-rankear
# Más candidatos = más cobertura, pero re-ranking más lento
RETRIEVAL_CANDIDATES = 15

# Cantidad de documentos que quedan DESPUÉS de re-rankear
RERANK_TOP_N = 3


@lru_cache(maxsize=1)
def _get_cross_encoder():
    """
    Carga el cross-encoder con lru_cache (singleton).

    El modelo se descarga en el primer uso (~66MB) y se mantiene
    en memoria para requests posteriores.

    Returns:
        CrossEncoder instance, o None si sentence-transformers no está instalado.
    """
    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder(CROSS_ENCODER_MODEL)
        logger.info(f"Cross-encoder cargado: {CROSS_ENCODER_MODEL}")
        return model
    except ImportError:
        logger.warning(
            "sentence-transformers no instalado. Re-ranking desactivado. "
            "Instala con: pip install sentence-transformers"
        )
        return None


def rerank(query: str, documents: List[Document], top_n: int = RERANK_TOP_N) -> List[Document]:
    """
    Re-rankea documentos usando un cross-encoder.

    Si sentence-transformers no está instalado (graceful degradation),
    retorna los primeros top_n documentos sin re-rankear.

    Args:
        query:     pregunta del usuario
        documents: candidatos del retrieval inicial (bi-encoder)
        top_n:     cuántos documentos retener después del re-ranking

    Returns:
        Lista de documentos re-ordenados por relevancia, limitada a top_n.
    """
    if not documents:
        return []

    # Graceful degradation: si no hay cross-encoder, truncar sin re-rankear
    cross_encoder = _get_cross_encoder()
    if cross_encoder is None:
        logger.info("Re-ranking omitido (sentence-transformers no disponible)")
        return documents[:top_n]

    # Construir pares (query, passage) para el cross-encoder
    pairs = [(query, doc.page_content) for doc in documents]

    # predict() retorna un array de scores (float) uno por par
    # Valores más altos = más relevante
    scores: list = cross_encoder.predict(pairs).tolist()

    # Ordenar documentos por score descendente
    scored_docs = sorted(zip(scores, documents), key=lambda x: x[0], reverse=True)

    top_docs = [doc for _, doc in scored_docs[:top_n]]

    logger.info(
        f"Re-ranking: {len(documents)} candidatos → {len(top_docs)} docs. "
        f"Scores top-3: {[f'{s:.3f}' for s, _ in scored_docs[:top_n]]}"
    )
    return top_docs
