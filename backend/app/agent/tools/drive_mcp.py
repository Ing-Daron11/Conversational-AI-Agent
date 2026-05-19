"""
drive_mcp.py — MCP Tool: Google Drive

CONCEPTO:
  Google Drive actúa como repositorio de documentos del usuario.
  Esta tool permite al agente buscar y leer archivos de Drive para
  luego ingestionarlos en la BD vectorial (Chroma).

  Flujo de uso típico:
    Admin sube PDF a Drive
      → search_drive_files("módulo 3") → encuentra el archivo
      → read_drive_file(file_id) → descarga el contenido
      → ingest_file(contenido) → indexa en Chroma
      → Ahora el usuario puede preguntar sobre ese documento por WhatsApp
"""

import io
import logging
import os

from langchain_core.tools import tool
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

logger = logging.getLogger(__name__)

TOKEN_PATH = os.path.join(os.path.dirname(__file__), "../../../../google_token.json")
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _get_drive_service():
    """Construye el cliente de Google Drive API autenticado."""
    token_path = os.path.abspath(TOKEN_PATH)
    if not os.path.exists(token_path):
        raise RuntimeError("No hay token de Google. Visita GET /auth/google para autenticar.")

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


@tool
def search_drive_files(query: str) -> str:
    """
    Busca archivos en Google Drive del usuario por nombre o contenido.
    Úsala cuando el usuario quiera encontrar un documento o archivo en Drive.

    Args:
        query: término de búsqueda (ej: "módulo 3", "apuntes de cálculo")

    Returns:
        Lista de archivos encontrados con su ID y nombre.
    """
    try:
        service = _get_drive_service()
        results = service.files().list(
            q=f"name contains '{query}' and trashed = false",
            fields="files(id, name, mimeType, modifiedTime)",
            pageSize=5,
        ).execute()

        files = results.get("files", [])
        if not files:
            return f"No encontré archivos que coincidan con '{query}' en Drive."

        lines = [f"Archivos encontrados para '{query}':"]
        for f in files:
            lines.append(f"• [{f['id']}] {f['name']} ({f['mimeType']})")
        return "\n".join(lines)

    except RuntimeError as e:
        return f"Error de autenticación: {e}"
    except Exception as e:
        logger.error(f"Error buscando en Drive: {e}")
        return f"Error al buscar en Drive: {e}"


@tool
def index_drive_file(file_id: str, file_name: str) -> str:
    """
    Descarga un archivo de Google Drive e lo indexa en la BD vectorial.
    Úsala cuando el usuario quiera agregar un documento de Drive a sus notas.

    Args:
        file_id: ID del archivo en Google Drive (obtenido con search_drive_files)
        file_name: nombre descriptivo para identificar el documento

    Returns:
        Confirmación del número de chunks indexados.
    """
    try:
        service = _get_drive_service()

        # Exportar como texto plano (para Google Docs) o descargar directo (para .pdf, .txt)
        file_meta = service.files().get(fileId=file_id, fields="mimeType, name").execute()
        mime = file_meta.get("mimeType", "")

        buffer = io.BytesIO()
        if "google-apps.document" in mime:
            # Google Doc → exportar como texto plano
            request = service.files().export_media(fileId=file_id, mimeType="text/plain")
        else:
            # PDF, TXT, etc. → descargar directo
            request = service.files().get_media(fileId=file_id)

        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        # Guardar temporalmente y usar el pipeline de ingestión
        tmp_path = f"/tmp/drive_{file_id}.txt"
        with open(tmp_path, "wb") as f:
            f.write(buffer.getvalue())

        from app.rag.ingestion import ingest_file
        chunks = ingest_file(tmp_path, metadata={"source": "google_drive", "drive_file": file_name})
        os.remove(tmp_path)

        return f"Archivo '{file_name}' indexado: {chunks} fragmentos disponibles para búsqueda."

    except RuntimeError as e:
        return f"Error de autenticación: {e}"
    except Exception as e:
        logger.error(f"Error indexando archivo de Drive: {e}")
        return f"Error al indexar el archivo: {e}"

