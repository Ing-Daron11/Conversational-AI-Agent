"""
ingest.py — Script CLI para indexar documentos en la BD vectorial

Uso:
    python ingest.py <ruta_al_archivo> [--materia NOMBRE] [--tipo TIPO]

Ejemplos:
    python ingest.py notas/transformers.txt --materia "IA2" --tipo "apunte"
    python ingest.py notas/modulo3.pdf --materia "Redes" --tipo "diapositivas"

Este script se ejecuta manualmente cuando quieres agregar nuevas notas.
En FASE 6 (Panel Admin) habrá una interfaz web para subir documentos.
"""

import argparse
import sys
import os

# Necesario para importar módulos de la app desde fuera del paquete
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.rag.ingestion import ingest_file


def main():
    parser = argparse.ArgumentParser(
        description="Indexa un archivo .txt o .pdf en la BD vectorial (Chroma)"
    )
    parser.add_argument("file", help="Ruta al archivo a indexar")
    parser.add_argument("--materia", default="", help="Nombre de la materia (metadato)")
    parser.add_argument("--tipo", default="apunte", help="Tipo de documento: apunte, diapositiva, examen...")

    args = parser.parse_args()

    metadata = {}
    if args.materia:
        metadata["materia"] = args.materia
    if args.tipo:
        metadata["tipo"] = args.tipo

    print(f"Indexando: {args.file}")
    print(f"Metadatos: {metadata}")

    chunks_count = ingest_file(file_path=args.file, metadata=metadata)
    print(f"Listo. {chunks_count} chunks indexados en Chroma.")


if __name__ == "__main__":
    main()
