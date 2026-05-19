"""
ingestion.py — Pipeline de ingestión de documentos para RAG

CONCEPTO — Chunking:
  Los LLMs tienen una ventana de contexto limitada (~128K tokens en GPT-4o,
  pero inyectar un documento entero en cada prompt es costoso y ruidoso).
  La solución: dividir los documentos en CHUNKS (fragmentos) antes de
  indexarlos. Así solo recuperamos los fragmentos RELEVANTES para cada
  pregunta, no el documento completo.

  Parámetros clave:
    chunk_size=512   → cada chunk tiene máximo 512 tokens
    chunk_overlap=50 → los últimos 50 tokens de un chunk se repiten al
                       inicio del siguiente, para no cortar ideas a la mitad.

  Ejemplo visual:
    Documento: [----chunk1----][--overlap--][----chunk2----][--overlap--][----chunk3----]

FLUJO COMPLETO:
  Archivo (.txt / .pdf)
    → TextLoader / PyPDFLoader          (lectura)
    → RecursiveCharacterTextSplitter    (chunking)
    → OpenAIEmbeddings.embed_documents  (vectorización)
    → Chroma.add_documents              (almacenamiento)
"""

import logging
from pathlib import Path
from typing import Optional

from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma

from app.rag.embeddings import get_embedding_model
from app.config import get_settings

logger = logging.getLogger(__name__)

# Parámetros de chunking — ajustables según el tipo de documento
CHUNK_SIZE = 512     # tokens por fragmento
CHUNK_OVERLAP = 50   # tokens de solapamiento entre fragmentos consecutivos


def get_vector_store(collection_name: str = "notas") -> Chroma:
    """
    Retorna (o crea) una colección Chroma en disco.

    En FASE 5 introduciremos colecciones separadas por categoría
    (notas, eventos, tareas) como estrategia de sharding.

    Chroma persiste los datos en CHROMA_PERSIST_PATH para que
    sobrevivan entre reinicios del servidor.
    """
    settings = get_settings()
    return Chroma(
        collection_name=collection_name,
        embedding_function=get_embedding_model(),
        persist_directory=settings.chroma_persist_path,
    )


def ingest_file(file_path: str, metadata: Optional[dict] = None) -> int:
    """
    Ingesta un archivo de texto o PDF en la BD vectorial.

    Args:
        file_path: ruta al archivo .txt o .pdf
        metadata: diccionario con metadatos adicionales, ej:
                  {"materia": "IA2", "tipo": "apunte", "semana": 3}
                  Los metadatos se almacenan junto al vector y permiten
                  filtrar búsquedas en FASE 5 (ej: solo notas de esta semana).

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

    # 2. CHUNKING — dividimos en fragmentos manejables
    # RecursiveCharacterTextSplitter intenta dividir por párrafos (\n\n),
    # luego por saltos de línea (\n), luego por espacios, etc.
    # Esto preserva la coherencia semántica mejor que cortar cada N caracteres.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,  # en FASE 5 podemos usar un tokenizer real
    )
    chunks = splitter.split_documents(documents)

    # 3. ENRIQUECIMIENTO DE METADATOS
    # Agregamos el nombre del archivo y metadatos personalizados a cada chunk.
    # En FASE 5 estos metadatos se usarán para filtrar antes del top-k search.
    for chunk in chunks:
        chunk.metadata["source_file"] = path.name
        if metadata:
            chunk.metadata.update(metadata)

    # 4. VECTORIZACIÓN + ALMACENAMIENTO en Chroma
    # Este paso llama a OpenAI Embeddings API por cada chunk y guarda
    # el vector resultante junto al texto y metadatos en Chroma.
    vector_store = get_vector_store()
    vector_store.add_documents(chunks)

    logger.info(f"Indexados {len(chunks)} chunks de '{path.name}' en Chroma")
    return len(chunks)
