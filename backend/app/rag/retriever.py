"""
retriever.py — Búsqueda semántica con pipeline de dos etapas (FASE 5)

PIPELINE FASE 5 (bi-encoder + cross-encoder):
  Paso 1 — RETRIEVAL rápido (bi-encoder, Chroma/Pinecone):
    query → embedding (nomic-embed-text)
    → similitud coseno contra todos los vectores
    → top-15 candidatos (rápido, aproximado)

  Paso 2 — RE-RANKING preciso (cross-encoder, CPU local):
    [(query, doc1), ..., (query, doc15)] → CrossEncoder.predict()
    → score de relevancia por par
    → top-3 documentos más relevantes (lento pero preciso)

  Paso 3 — BÚSQUEDA MULTI-SHARD (opcional):
    Si collection_name="all", busca en notas + tareas + examenes
    y agrega los resultados antes de re-rankear.

DIFERENCIA vs FASE 1:
  Fase 1: bi-encoder retrieval → top-3 directo (simple, puede devolver resultados poco relevantes)
  Fase 5: bi-encoder top-15 → cross-encoder rerank → top-3 (más preciso, latencia ~+50ms)

NOTA ACADÉMICA — Similitud coseno vs L2:
  Coseno mide el ÁNGULO entre vectores (ignora magnitud).
  L2 (Euclidiana) mide la DISTANCIA absoluta.
  Para texto semántico, coseno es preferido: un texto corto y uno largo
  sobre el mismo tema tendrán vectores similares en dirección aunque
  difieran en magnitud.
"""

import logging
from typing import List

from langchain.schema import Document

from app.rag.vectorstore import get_vector_store, ALL_COLLECTIONS
from app.rag.reranker import rerank, RETRIEVAL_CANDIDATES

logger = logging.getLogger(__name__)

FINAL_TOP_K = 3  # fragmentos que llegan al LLM


def _retrieve_from_collection(query: str, collection: str, k: int) -> List[Document]:
    """Recupera candidatos de una colección específica."""
    try:
        store = get_vector_store(collection)
        # Verificar si la colección tiene documentos (solo Chroma)
        if hasattr(store, "_collection") and store._collection.count() == 0:
            return []
        return store.similarity_search(query, k=k)
    except Exception as e:
        logger.warning(f"Error buscando en colección '{collection}': {e}")
        return []


def retrieve_context(
    query: str,
    k: int = FINAL_TOP_K,
    collection: str = "notas",
) -> str:
    """
    Pipeline completo: retrieval bi-encoder + re-ranking cross-encoder.

    Args:
        query:      pregunta del usuario
        k:          número de fragmentos finales para el LLM
        collection: colección donde buscar. Usa "all" para buscar en todos los shards.

    Returns:
        Texto con los k fragmentos más relevantes, listos para inyectar al LLM.
        Retorna string vacío si no hay documentos indexados.
    """
    # ── Paso 1: Retrieval inicial (multi-shard o colección específica) ───────
    if collection == "all":
        # Buscar en todos los shards y agregar candidatos
        candidates: List[Document] = []
        for col in ALL_COLLECTIONS:
            partial = _retrieve_from_collection(query, col, k=RETRIEVAL_CANDIDATES // len(ALL_COLLECTIONS))
            candidates.extend(partial)
        logger.info(f"Multi-shard retrieval: {len(candidates)} candidatos totales de {len(ALL_COLLECTIONS)} colecciones")
    else:
        candidates = _retrieve_from_collection(query, collection, k=RETRIEVAL_CANDIDATES)
        logger.info(f"Retrieval de '{collection}': {len(candidates)} candidatos")

    if not candidates:
        logger.warning("BD vectorial vacía o sin resultados. Ejecuta el script de ingestión.")
        return ""

    # ── Paso 2: Re-ranking con cross-encoder ─────────────────────────────────
    # Si hay pocos candidatos (< FINAL_TOP_K), no tiene sentido re-rankear
    if len(candidates) <= k:
        top_docs = candidates
    else:
        top_docs = rerank(query, candidates, top_n=k)

    if not top_docs:
        return ""

    # ── Paso 3: Formateo del contexto para el LLM ────────────────────────────
    # Incluimos la fuente de cada fragmento para que el LLM pueda citar
    context_parts = []
    for i, doc in enumerate(top_docs, start=1):
        source = doc.metadata.get("source_file", "desconocido")
        materia = doc.metadata.get("materia", "")
        label = f"[Fragmento {i} — {source}"
        if materia:
            label += f" | {materia}"
        label += "]"
        context_parts.append(f"{label}\n{doc.page_content}")

    context = "\n\n---\n\n".join(context_parts)
    logger.info(f"Contexto RAG listo: {len(top_docs)} fragmentos para query: {query!r}")
    return context


def list_indexed_documents(collection: str = "notas") -> List[dict]:
    """
    Lista los documentos indexados con sus metadatos.
    Usado por el endpoint GET /admin/documents del panel admin (FASE 6).

    Returns:
        Lista de dicts con {source_file, materia, tipo, chunk_count}
    """
    try:
        store = get_vector_store(collection)
        if not hasattr(store, "_collection"):
            return []  # Pinecone no soporta esta operación directamente

        result = store._collection.get(include=["metadatas"])
        metadatas = result.get("metadatas", [])

        # Agrupar por archivo fuente y contar chunks
        file_groups: dict = {}
        for meta in metadatas:
            key = meta.get("source_file", "desconocido")
            if key not in file_groups:
                file_groups[key] = {
                    "source_file": key,
                    "materia": meta.get("materia", ""),
                    "tipo": meta.get("tipo", ""),
                    "collection": collection,
                    "chunk_count": 0,
                }
            file_groups[key]["chunk_count"] += 1

        return list(file_groups.values())

    except Exception as e:
        logger.error(f"Error listando documentos: {e}")
        return []

