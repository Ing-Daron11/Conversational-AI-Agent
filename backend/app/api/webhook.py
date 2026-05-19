"""
webhook.py — Endpoint de recepción de mensajes de WhatsApp (Twilio)

FLUJO FASE 2 (RAG + Memoria):
  1. Twilio hace POST con el mensaje del usuario (form-data)
  2. Extraemos el texto (Body) y el remitente (From)
  3. Cargamos el historial de conversación desde Redis
  4. El retriever busca los top-k fragmentos relevantes en Chroma
  5. Construimos el prompt: system(RAG) + history + mensaje_actual
  6. El LLM (Qwen3:4b vía Ollama) genera la respuesta con todo el contexto
  7. Guardamos el par (usuario, asistente) en Redis (TTL 30 min)
  8. BackgroundTask: persiste el historial en PostgreSQL
  9. Devolvemos la respuesta en TwiML

CONCEPTO TwiML:
  Twilio Markup Language — el XML que Twilio interpreta para saber
  qué mensaje enviar de vuelta. Respondemos al mismo HTTP request
  con Content-Type: application/xml.
"""

import logging
from fastapi import APIRouter, BackgroundTasks, Form, Request, Response
from langchain_ollama import ChatOllama
from langchain.schema import SystemMessage, HumanMessage

from app.agent.memory import ConversationMemory
from app.models.database import save_conversation_to_db
from app.rag.retriever import retrieve_context
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()

# ---- Prompt del sistema ----
# Contiene dos placeholders que se inyectan en cada request:
#   {retrieved_context} → fragmentos recuperados por el retriever (RAG)
#   {conversation_history} → resumen del historial (para orientación del LLM)
# El historial completo se pasa como mensajes separados (HumanMessage/AIMessage),
# no como texto plano, para que el LLM lo entienda como una conversación real.
SYSTEM_PROMPT_TEMPLATE = """Eres un asistente académico personal amigable y preciso.
Tu usuario te contacta por WhatsApp para gestionar su vida académica.

CAPACIDADES:
- Buscar información en sus notas y apuntes almacenados
- Responder preguntas académicas generales
- Recordar lo que el usuario mencionó anteriormente en esta conversación

CONTEXTO RECUPERADO (RAG):
{retrieved_context}

REGLAS:
- Responde siempre en español, de forma concisa (máximo 3-4 oraciones para WhatsApp)
- Si no encuentras información en el contexto RAG, dilo claramente en lugar de inventar
- Usa el historial de conversación para dar respuestas coherentes y personalizadas
- Si el usuario saluda, responde brevemente y pregunta en qué puedes ayudar"""


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


def get_llm() -> ChatOllama:
    """Instancia el LLM local con Ollama (todo corre en tu máquina)."""
    return ChatOllama(
        model=settings.ollama_model,
        temperature=settings.llm_temperature,
        num_predict=settings.llm_max_tokens,
        base_url=settings.ollama_base_url,
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
    Endpoint principal del webhook — pipeline RAG + Memoria (FASE 2).

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
    # Obtenemos los mensajes anteriores de esta sesión (últimos 10).
    # Si es la primera vez que el usuario escribe (o el TTL expiró),
    # history será una lista vacía [].
    history = await ConversationMemory.get_history(From)
    history_messages = ConversationMemory.to_langchain_messages(history)
    logger.info(f"Historial cargado para {From}: {len(history_messages)} mensajes previos")

    # --- PASO 2: RETRIEVAL — buscar contexto relevante en Chroma ---
    retrieved_context = retrieve_context(query=user_message)
    if retrieved_context:
        logger.info("Contexto RAG recuperado.")
    else:
        logger.info("Sin contexto RAG, LLM responderá con conocimiento general.")

    # --- PASO 3: CONSTRUCCIÓN DEL PROMPT ---
    # Estructura final que recibe el LLM:
    #
    #   SystemMessage  → personalidad + contexto RAG
    #   HumanMessage   → "me llamo Juan"           ┐
    #   AIMessage      → "Hola Juan, ¿en qué..."   │ historial previo
    #   HumanMessage   → "¿qué tengo mañana?"      ┘
    #   HumanMessage   → mensaje actual del usuario
    #
    # El LLM ve toda la conversación y puede referirse a mensajes anteriores.
    system_content = SYSTEM_PROMPT_TEMPLATE.format(
        retrieved_context=retrieved_context or "No hay información disponible en las notas."
    )

    messages = (
        [SystemMessage(content=system_content)]
        + history_messages                          # conversación previa
        + [HumanMessage(content=user_message)]      # mensaje actual
    )

    # --- PASO 4: GENERATION — el LLM genera la respuesta ---
    llm = get_llm()
    response = await llm.ainvoke(messages)
    reply = response.content.strip()
    logger.info(f"Respuesta LLM a {From}: {reply!r}")

    # --- PASO 5: ACTUALIZAR MEMORIA en Redis ---
    # Guardamos el par (usuario, asistente) y reiniciamos el TTL de 30 min.
    await ConversationMemory.add_messages(From, user_message, reply)

    # --- PASO 6: PERSISTIR en PostgreSQL (background, sin bloquear) ---
    # Recargamos el historial actualizado para guardarlo completo en la BD.
    updated_history = await ConversationMemory.get_history(From)
    background_tasks.add_task(save_conversation_to_db, From, updated_history)

    # --- PASO 7: RESPUESTA TwiML ---
    twiml = build_twiml_response(reply)
    return Response(content=twiml, media_type="application/xml")

