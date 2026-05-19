"""
ingestion.py — Pipeline de ingestión de documentos para RAG

TODO: Implementar en FASE 1
Responsabilidad:
  - Leer archivos .txt / .pdf
  - Dividir en chunks (chunk_size=512, overlap=50) → estrategia en FASE 5
  - Generar embeddings de cada chunk con OpenAI text-embedding-3-small
  - Almacenar vectores + metadatos en Chroma

CONCEPTO RAG — Ingestión:
  Los documentos no se guardan como texto plano; se convierten en
  vectores numéricos (embeddings) que representan su significado
  semántico. Documentos similares quedan "cerca" en el espacio vectorial.
"""

# Este módulo se implementa en FASE 1
