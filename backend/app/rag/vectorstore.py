"""
vectorstore.py — Capa de abstracción para BD vectorial (Chroma ↔ Pinecone)

CONCEPTO — ¿Por qué abstraer el vectorstore?
  En desarrollo usamos ChromaDB: es local, sin costo, sin configuración extra.
  En producción usamos Pinecone: es un servicio gestionado, escalable,
  con réplicas y sharding automático.

  Con esta abstracción, el resto del código (ingestion.py, retriever.py)
  no sabe si está hablando con Chroma o Pinecone: siempre usa
  `get_vector_store()` y el sistema elige según USE_PINECONE en el .env.

CONCEPTO — Sharding en vectorstores:
  Sharding = dividir los datos en múltiples particiones independientes.

  En este sistema usamos sharding LÓGICO por categoría de documento:
    - "notas"    → apuntes de clase y resúmenes de estudio
    - "tareas"   → enunciados de tareas y proyectos
    - "examenes" → guías de examen y material de repaso

  Beneficios:
    1. Búsquedas más precisas: solo buscamos en la colección relevante
    2. Menor ruido en resultados
    3. Fácil de limpiar o actualizar por categoría

  Implementación:
    - Chroma:   colecciones separadas → collection_name = "notas", "tareas", etc.
    - Pinecone: namespaces dentro del mismo índice → namespace = "notas", etc.

CONCEPTO — Pinecone (nube):
  Pinecone es una BD vectorial serverless. Ventajas sobre Chroma local:
    - Sharding y réplicas automáticos (escala a millones de vectores)
    - Búsqueda en <50ms con índice HNSW optimizado
    - Sin mantenimiento de infraestructura
    - Filtrado por metadatos antes del ANN search (metadata pre-filtering)
  
  Configuración:
    USE_PINECONE=true
    PINECONE_API_KEY=<clave desde app.pinecone.io>
    PINECONE_INDEX_NAME=academic-notes
"""

import logging
from functools import lru_cache
from typing import Literal

from langchain_community.vectorstores import Chroma
from langchain_core.vectorstores import VectorStore

from app.rag.embeddings import get_embedding_model
from app.config import get_settings

logger = logging.getLogger(__name__)

# Colecciones válidas para sharding lógico
CollectionName = Literal["notas", "tareas", "examenes"]
ALL_COLLECTIONS: list[str] = ["notas", "tareas", "examenes"]


def _get_chroma_store(collection_name: str) -> Chroma:
    """
    Crea/recupera una colección ChromaDB local.

    Cada colección es una partición independiente en disco.
    Las colecciones comparten el mismo directorio de persistencia
    pero son completamente independientes entre sí.
    """
    settings = get_settings()
    return Chroma(
        collection_name=collection_name,
        embedding_function=get_embedding_model(),
        persist_directory=settings.chroma_persist_path,
    )


def _get_pinecone_store(collection_name: str) -> VectorStore:
    """
    Crea/recupera un namespace de Pinecone.

    Pinecone usa el concepto de 'namespace' dentro de un índice para
    separar los datos. Es equivalente a una colección en Chroma pero
    en la nube con sharding automático.

    Requiere PINECONE_API_KEY y PINECONE_INDEX_NAME en el .env.
    """
    settings = get_settings()
    try:
        from pinecone import Pinecone as PineconeClient
        from langchain_pinecone import PineconeVectorStore

        pc = PineconeClient(api_key=settings.pinecone_api_key)
        index = pc.Index(settings.pinecone_index_name)

        store = PineconeVectorStore(
            index=index,
            embedding=get_embedding_model(),
            namespace=collection_name,  # sharding por namespace
        )
        logger.info(f"Conectado a Pinecone: index={settings.pinecone_index_name}, ns={collection_name}")
        return store

    except ImportError:
        logger.error("langchain-pinecone no instalado. Usa: pip install langchain-pinecone pinecone")
        raise
    except Exception as e:
        logger.error(f"Error conectando a Pinecone: {e}")
        raise


def get_vector_store(collection_name: str = "notas") -> VectorStore:
    """
    Factory principal: retorna Chroma o Pinecone según configuración.

    Modo selección (en .env):
      USE_PINECONE=false → ChromaDB local  (desarrollo, sin costo)
      USE_PINECONE=true  → Pinecone cloud  (producción, escalable)

    Args:
        collection_name: shard/partición a usar ("notas", "tareas", "examenes")

    Returns:
        VectorStore listo para add_documents() y similarity_search()
    """
    settings = get_settings()

    if settings.use_pinecone and settings.pinecone_api_key:
        logger.debug(f"Vectorstore: Pinecone (namespace={collection_name})")
        return _get_pinecone_store(collection_name)

    logger.debug(f"Vectorstore: ChromaDB (collection={collection_name})")
    return _get_chroma_store(collection_name)


def get_collection_stats() -> dict:
    """
    Retorna el número de documentos indexados por colección (solo Chroma).
    Usado por el endpoint /admin/stats.
    """
    settings = get_settings()

    if settings.use_pinecone and settings.pinecone_api_key:
        return {"nota": "stats de Pinecone no disponibles en esta versión"}

    stats = {}
    for col in ALL_COLLECTIONS:
        try:
            store = _get_chroma_store(col)
            count = store._collection.count()
            stats[col] = count
        except Exception:
            stats[col] = 0

    stats["total"] = sum(stats.values())
    return stats
