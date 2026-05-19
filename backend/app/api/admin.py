"""
admin.py — API REST para el panel de administración (FASE 6)

Estos endpoints son consumidos por el frontend Next.js en FASE 6.
No están protegidos con autenticación en desarrollo, pero en producción
deberían requerir un token JWT o sesión.

ENDPOINTS:
  GET  /admin/stats       → métricas del sistema (docs, conversaciones, sesiones)
  GET  /admin/documents   → lista de documentos indexados por colección
  POST /admin/ingest      → subir y indexar un nuevo documento
  GET  /admin/events      → próximos eventos del Google Calendar

CONCEPTO — ¿Por qué un panel de administración?
  En un sistema RAG en producción necesitamos:
    1. Monitorear qué documentos están indexados (y en qué shard)
    2. Agregar nuevos documentos sin acceso al servidor vía CLI
    3. Ver métricas de uso (conversaciones activas, docs por materia)
    4. Verificar la integración con Google Calendar

  El frontend Next.js actúa como cliente de estos endpoints,
  proporcionando una interfaz visual amigable.
"""

import logging
import os
import tempfile
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Modelos de respuesta (Pydantic) ───────────────────────────────────────

class CollectionStats(BaseModel):
    collection: str
    doc_count: int


class SystemStats(BaseModel):
    docs_per_collection: dict
    total_docs: int
    total_conversations: int
    redis_active_sessions: int
    version: str = "0.4.0"


class DocumentItem(BaseModel):
    source_file: str
    materia: str
    tipo: str
    collection: str
    chunk_count: int


class IngestResponse(BaseModel):
    success: bool
    chunks_indexed: int
    file_name: str
    collection: str
    message: str


# ─── GET /admin/stats ───────────────────────────────────────────────────────

@router.get("/stats", response_model=SystemStats)
async def get_stats():
    """
    Retorna métricas generales del sistema:
      - docs_per_collection: chunks indexados por shard (notas, tareas, examenes)
      - total_conversations: registros en PostgreSQL
      - redis_active_sessions: sesiones activas en Redis

    CONCEPTO — ¿Por qué monitorear estas métricas?
      Un chatbot RAG puede fallar silenciosamente si:
        1. La BD vectorial está vacía (no hay contexto para el LLM)
        2. Redis perdió las sesiones (el bot "olvida" la conversación)
        3. PostgreSQL tiene demasiadas conversaciones (necesita limpieza)
    """
    # 1. Estadísticas de la BD vectorial (ChromaDB)
    from app.rag.vectorstore import get_collection_stats
    collection_stats = get_collection_stats()
    total_docs = collection_stats.pop("total", 0)

    # 2. Total de conversaciones en PostgreSQL
    total_conversations = 0
    try:
        from app.models.database import SessionLocal
        from app.models.database import ConversationMessage
        db = SessionLocal()
        total_conversations = db.query(ConversationMessage).count()
        db.close()
    except Exception as e:
        logger.warning(f"No se pudo consultar PostgreSQL: {e}")

    # 3. Sesiones activas en Redis (claves con patrón "session:*")
    redis_active_sessions = 0
    try:
        import redis as redis_lib
        from app.config import get_settings
        settings = get_settings()
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        keys = r.keys("session:*")
        redis_active_sessions = len(keys)
    except Exception as e:
        logger.warning(f"No se pudo consultar Redis: {e}")

    return SystemStats(
        docs_per_collection=collection_stats,
        total_docs=total_docs,
        total_conversations=total_conversations,
        redis_active_sessions=redis_active_sessions,
    )


# ─── GET /admin/documents ───────────────────────────────────────────────────

@router.get("/documents", response_model=List[DocumentItem])
async def list_documents(
    collection: Optional[str] = Query(None, description="Filtrar por colección: notas, tareas, examenes")
):
    """
    Lista los documentos indexados con sus metadatos.

    Si se especifica `collection`, solo devuelve docs de ese shard.
    Si no, devuelve docs de todos los shards.

    CONCEPTO — Metadatos en vectorstores:
      Cada chunk almacenado tiene un vector (embedding) + metadatos (dict).
      Los metadatos permiten filtrar ANTES de la búsqueda vectorial
      (ej: "busca solo en documentos de la materia IA2").
      ChromaDB soporta filtros de metadatos en `similarity_search(where={...})`.
    """
    from app.rag.retriever import list_indexed_documents
    from app.rag.vectorstore import ALL_COLLECTIONS

    collections_to_query = [collection] if collection else ALL_COLLECTIONS
    all_docs: List[DocumentItem] = []

    for col in collections_to_query:
        docs = list_indexed_documents(col)
        all_docs.extend([
            DocumentItem(
                source_file=d.get("source_file", ""),
                materia=d.get("materia", ""),
                tipo=d.get("tipo", ""),
                collection=d.get("collection", col),
                chunk_count=d.get("chunk_count", 0),
            )
            for d in docs
        ])

    return all_docs


# ─── POST /admin/ingest ─────────────────────────────────────────────────────

@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    file: UploadFile = File(..., description="Archivo .txt o .pdf a indexar"),
    collection: str = Form(default="notas", description="Shard destino: notas | tareas | examenes"),
    materia: str = Form(default="", description="Nombre de la materia (metadato)"),
    tipo: str = Form(default="apunte", description="Tipo de documento: apunte | tarea | examen"),
):
    """
    Sube un archivo y lo ingesta en la BD vectorial.

    Flujo:
      1. Recibe el archivo vía multipart/form-data
      2. Guarda en directorio temporal del sistema (tempfile)
      3. Llama a ingest_file() → chunking → embedding → Chroma/Pinecone
      4. Borra el archivo temporal
      5. Retorna cuántos chunks fueron indexados

    SEGURIDAD:
      - Solo acepta extensiones .txt y .pdf
      - Usa tempfile del sistema (no paths controlados por el cliente)
      - El nombre de archivo se sanitiza con os.path.basename
    """
    # Validar extensión
    allowed_ext = {".txt", ".pdf"}
    filename = os.path.basename(file.filename or "upload")
    ext = os.path.splitext(filename)[1].lower()

    if ext not in allowed_ext:
        raise HTTPException(
            status_code=400,
            detail=f"Extensión no permitida: {ext}. Solo se aceptan .txt y .pdf"
        )

    # Validar colección
    from app.rag.vectorstore import ALL_COLLECTIONS
    if collection not in ALL_COLLECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Colección inválida: '{collection}'. Opciones: {ALL_COLLECTIONS}"
        )

    # Guardar en temp y procesar
    tmp_path = None
    try:
        # Crear archivo temporal con la extensión correcta preservada
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=ext,
            prefix="ingest_",
        ) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        from app.rag.ingestion import ingest_file
        metadata = {"materia": materia, "tipo": tipo}
        chunks_indexed = ingest_file(
            file_path=tmp_path,
            metadata=metadata,
            collection_name=collection,
        )

        logger.info(f"Ingesta exitosa: {filename} → {chunks_indexed} chunks en '{collection}'")
        return IngestResponse(
            success=True,
            chunks_indexed=chunks_indexed,
            file_name=filename,
            collection=collection,
            message=f"'{filename}' indexado exitosamente en la colección '{collection}'.",
        )

    except Exception as e:
        logger.error(f"Error en ingestión de {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Siempre limpiamos el archivo temporal
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ─── GET /admin/events ──────────────────────────────────────────────────────

@router.get("/events")
async def get_calendar_events(
    start: str = Query(default=None, description="Fecha inicio YYYY-MM-DD"),
    end: str = Query(default=None, description="Fecha fin YYYY-MM-DD"),
    max_results: int = Query(default=10, ge=1, le=50),
):
    """
    Lista los próximos eventos del Google Calendar.

    Usa el token OAuth2 guardado en google_token.json (autenticación con /auth/google).
    Si el token no existe, retorna instrucciones para autenticarse.

    Args:
        start: fecha de inicio en formato YYYY-MM-DD (default: hoy)
        end:   fecha de fin en formato YYYY-MM-DD (default: 30 días desde hoy)
        max_results: máximo de eventos a retornar (1-50)

    NOTA: Este endpoint actúa como proxy entre el frontend y Google Calendar API.
    Evita que el frontend necesite manejar las credenciales OAuth directamente.
    """
    from pathlib import Path
    import datetime

    token_path = Path("google_token.json")
    if not token_path.exists():
        return {
            "authenticated": False,
            "message": "No autenticado. Visita /auth/google para conectar Google Calendar.",
            "auth_url": "/auth/google",
            "events": [],
        }

    try:
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(
            str(token_path),
            scopes=["https://www.googleapis.com/auth/calendar.readonly"],
        )
        service = build("calendar", "v3", credentials=creds)

        # Determinar rango de fechas
        now = datetime.datetime.utcnow()
        time_min = f"{start}T00:00:00Z" if start else now.isoformat() + "Z"
        time_max = f"{end}T23:59:59Z" if end else (now + datetime.timedelta(days=30)).isoformat() + "Z"

        events_result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = events_result.get("items", [])
        formatted = [
            {
                "id": e.get("id"),
                "summary": e.get("summary", "Sin título"),
                "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
                "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
                "description": e.get("description", ""),
            }
            for e in events
        ]

        return {"authenticated": True, "events": formatted, "count": len(formatted)}

    except Exception as e:
        logger.error(f"Error obteniendo eventos de Google Calendar: {e}")
        raise HTTPException(status_code=500, detail=f"Error con Google Calendar: {str(e)}")
