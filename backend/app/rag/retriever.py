"""
retriever.py — Búsqueda semántica en la BD vectorial

TODO: Implementar en FASE 1
Responsabilidad:
  - Dado un query de texto, generar su embedding
  - Buscar los top-k fragmentos más cercanos en Chroma
  - Retornar los fragmentos como contexto para el LLM

CONCEPTO RAG — Retrieval:
  El retriever es el corazón del pipeline RAG. Convierte la pregunta
  del usuario en un vector y hace una búsqueda de similitud coseno
  contra todos los documentos indexados. Los k más cercanos se
  inyectan como contexto en el prompt del LLM.
"""

# Este módulo se implementa en FASE 1
