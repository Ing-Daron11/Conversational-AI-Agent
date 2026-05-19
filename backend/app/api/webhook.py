"""
webhook.py — Endpoint de recepción de mensajes de WhatsApp (Twilio)

FLUJO FASE 3 (Agente MCP + RAG dinámico + Memoria):
  1. Twilio hace POST con el mensaje del usuario (form-data)
  2. Extraemos el texto (Body) y el remitente (From)
  3. Cargamos el historial de conversación desde Redis
  4. Pasamos todo al AgentExecutor (orchestrator.py)
     - El agente DECIDE si necesita buscar notas (search_notes)
     - El agente DECIDE si necesita consultar Calendar (list_calendar_events)
     - El agente DECIDE si necesita crear un evento (create_calendar_event)
     - O simplemente responde con conocimiento general
  5. Guardamos la respuesta en Redis (TTL 30 min)
  6. BackgroundTask: persiste en PostgreSQL
  7. Devolvemos la respuesta en TwiML

DIFERENCIA vs FASE 2:
  - Fase 2: RAG siempre se ejecuta, sin herramientas de Calendar
  - Fase 3: RAG es una tool opcional, más Calendar, más Drive
            El LLM decide cuándo y qué usar → más eficiente y capaz

CONCEPTO TwiML:
  Twilio Markup Language — XML que Twilio interpreta para saber
  qué mensaje enviar de vuelta al usuario de WhatsApp.
"""

import logging
from fastapi import APIRouter, BackgroundTasks, Form, Request, Response

from app.agent.memory import ConversationMemory
from app.agent.orchestrator import run_agent
from app.models.database import save_conversation_to_db

logger = logging.getLogger(__name__)

router = APIRouter()


def build_twiml_response(message: str) -> str:
    """
    Construye una respuesta TwiML (Twilio Markup Language).
    Escapamos &, < y > para garantizar XML válido (output encoding).
    """
    safe_message = (
        message.replace("&", "&amp;")
               .replace("<", "&lt;")
               .replace(">", "&gt;")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Message>{safe_message}</Message>"
        "</Response>"
    )


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    Body: str = Form(default=""),
    From: str = Form(default=""),
    To: str = Form(default=""),
):
    """
    Endpoint principal del webhook — pipeline Agente MCP (FASE 3).

    background_tasks: FastAPI ejecuta estas tareas DESPUÉS de enviar la
    respuesta al cliente. Así la persistencia en PostgreSQL no agrega
    latencia visible al usuario.
    """
    user_message = Body.strip()
    logger.info(f"Mensaje de {From}: {user_message!r}")

    if not user_message:
        return Response(
            content=build_twiml_response("No recibí ningún mensaje. ¿En qué puedo ayudarte?"),
            media_type="application/xml",
        )

    # --- PASO 1: MEMORIA — cargar historial desde Redis ---
    history = await ConversationMemory.get_history(From)
    chat_history = ConversationMemory.to_langchain_messages(history)
    logger.info(f"Historial cargado: {len(chat_history)} mensajes previos")

    # --- PASO 2: AGENTE — decide tools y genera respuesta ---
    # El AgentExecutor internamente puede llamar:
    #   - search_notes(query) → RAG dinámico en Chroma
    #   - list_calendar_events(start, end) → Google Calendar
    #   - create_calendar_event(title, date, time, ...) → nueva cita
    #   - delete_calendar_event(title, date) → cancelar cita
    #   - search_drive_files(query) → buscar en Drive
    reply = await run_agent(user_message, chat_history)

    # --- PASO 3: ACTUALIZAR MEMORIA en Redis ---
    await ConversationMemory.add_messages(From, user_message, reply)

    # --- PASO 4: PERSISTIR en PostgreSQL (background, sin bloquear) ---
    updated_history = await ConversationMemory.get_history(From)
    background_tasks.add_task(save_conversation_to_db, From, updated_history)

    # --- PASO 5: RESPUESTA TwiML ---
    twiml = build_twiml_response(reply)
    return Response(content=twiml, media_type="application/xml")

