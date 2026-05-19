"""
ingestion.py — Pipeline de ingestión de documentos para RAG (FASE 5)

CONCEPTO — Chunking:
  Los LLMs tienen una ventana de contexto limitada.
  Dividimos los documentos en CHUNKS antes de indexar.
  Solo recuperamos los fragmentos RELEVANTES para cada pregunta.

  Parámetros:
    chunk_size=512   → máximo 512 caracteres por chunk
    chunk_overlap=50 → los últimos 50 chars de un chunk se repiten al
                       inicio del siguiente (no cortar ideas a la mitad)

CONCEPTO — Sharding lógico (FASE 5):
  Organizamos los documentos en colecciones separadas por categoría:
    "notas"    → apuntes de clase, resúmenes
    "tareas"   → enunciados de tareas y proyectos
    "examenes" → guías de estudio, material de repaso

  Beneficio: búsquedas más precisas al filtrar por categoría.
  El retriever puede buscar en la colección correcta según el contexto.

FLUJO COMPLETO:
  Archivo (.txt / .pdf)
    → TextLoader / PyPDFLoader          (lectura)
    → RecursiveCharacterTextSplitter    (chunking)
    → OllamaEmbeddings.embed_documents  (vectorización — nomic-embed-text)
    → Chroma/Pinecone.add_documents     (almacenamiento)
"""

import logging
from pathlib import Path
from typing import Optional

from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter

from app.rag.vectorstore import get_vector_store

logger = logging.getLogger(__name__)

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50


def ingest_file(
    file_path: str,
    metadata: Optional[dict] = None,
    collection_name: str = "notas",
) -> int:
    """
    Ingesta un archivo de texto o PDF en la BD vectorial.

    Args:
        file_path:       ruta al archivo .txt o .pdf
        metadata:        metadatos adicionales, ej:
                         {"materia": "IA2", "tipo": "apunte", "semana": 3}
        collection_name: shard donde almacenar ("notas", "tareas", "examenes")
                         Usar el shard correcto mejora la precisión del retrieval.

    Returns:
        Número de chunks indexados.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {file_path}")

    # 1. CARGA del documento según su extensión
    if path.suffix.lower() == ".pdf":
        loader = PyPDFLoader(str(path))
    else:
        loader = TextLoader(str(path), encoding="utf-8")

    documents = loader.load()
    logger.info(f"Cargado: {path.name} ({len(documents)} página/s)")

    # 2. CHUNKING
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    )
    chunks = splitter.split_documents(documents)

    # 3. ENRIQUECIMIENTO DE METADATOS
    for chunk in chunks:
        chunk.metadata["source_file"] = path.name
        chunk.metadata["collection"] = collection_name
        if metadata:
            chunk.metadata.update(metadata)

    # 4. VECTORIZACIÓN + ALMACENAMIENTO (Chroma o Pinecone según config)
    vector_store = get_vector_store(collection_name)
    vector_store.add_documents(chunks)

    logger.info(f"Indexados {len(chunks)} chunks de '{path.name}' en shard '{collection_name}'")
    return len(chunks)

