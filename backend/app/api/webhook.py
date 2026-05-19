"""
webhook.py — Endpoint de recepción de mensajes de WhatsApp (Twilio)

FLUJO FASE 1 (Pipeline RAG):
  1. Twilio hace POST con el mensaje del usuario (form-data)
  2. Extraemos el texto (Body) y el remitente (From)
  3. El retriever busca los top-k fragmentos relevantes en Chroma
  4. Construimos el prompt: system + contexto_RAG + mensaje_usuario
  5. El LLM (Qwen3:4b vía Ollama, local) genera la respuesta usando ese contexto
  6. Devolvemos la respuesta en TwiML para que Twilio la envíe al usuario

CONCEPTO TwiML:
  Twilio Markup Language — el XML que Twilio interpreta para saber
  qué mensaje enviar de vuelta. Respondemos al mismo HTTP request
  con Content-Type: application/xml.
"""

import logging
from fastapi import APIRouter, Form, Request, Response
from langchain_ollama import ChatOllama
from langchain.schema import SystemMessage, HumanMessage

from app.rag.retriever import retrieve_context
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()

# Prompt base del asistente — define su personalidad, capacidades y reglas.
# {retrieved_context} se reemplaza en tiempo de ejecución con los fragmentos
# recuperados por el retriever. Esto es la "G" de RAG: Generation con contexto.
SYSTEM_PROMPT_TEMPLATE = """Eres un asistente académico personal amigable y preciso.
Tu usuario te contacta por WhatsApp para gestionar su vida académica.

CAPACIDADES:
- Buscar información en sus notas y apuntes almacenados
- Responder preguntas académicas generales

CONTEXTO RECUPERADO (RAG):
{retrieved_context}

REGLAS:
- Responde siempre en español, de forma concisa (máximo 3-4 oraciones para WhatsApp)
- Si no encuentras información en el contexto, dilo claramente en lugar de inventar
- Usa el contexto recuperado cuando sea relevante
- Si el usuario saluda, responde brevemente y pregunta en qué puedes ayudar"""


def build_twiml_response(message: str) -> str:
    """
    Construye una respuesta TwiML (Twilio Markup Language).
    El tag <Message> indica el texto que Twilio enviará al usuario por WhatsApp.
    """
    # Escapamos caracteres XML para evitar romper el XML con mensajes que
    # contengan <, > o & (seguridad básica de output encoding).
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
    """
    Instancia el LLM local con Ollama.

    ChatOllama se comunica con el servidor Ollama corriendo en tu máquina
    (por defecto en http://localhost:11434). No envía datos a ningún servidor
    externo — todo corre localmente.

    num_predict equivale a max_tokens: límite de tokens en la respuesta.
    """
    return ChatOllama(
        model=settings.ollama_model,             # qwen3:4b por defecto
        temperature=settings.llm_temperature,    # 0.3 → respuestas precisas
        num_predict=settings.llm_max_tokens,     # 500 → adecuado para WhatsApp
        base_url=settings.ollama_base_url,
    )


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    Body: str = Form(default=""),    # texto del mensaje del usuario
    From: str = Form(default=""),    # número remitente (ej: whatsapp:+5219...)
    To: str = Form(default=""),      # número Twilio receptor
):
    """
    Endpoint principal del webhook — pipeline RAG completo (FASE 1).

    Twilio envía los datos como form-data (application/x-www-form-urlencoded).

    En FASE 2 se agregará historial de conversación (memoria con Redis).
    En FASE 3 se agregarán MCP tools para Google Calendar.
    """
    user_message = Body.strip()
    logger.info(f"Mensaje recibido de {From}: {user_message!r}")

    if not user_message:
        return Response(
            content=build_twiml_response("No recibí ningún mensaje. ¿En qué puedo ayudarte?"),
            media_type="application/xml",
        )

    # --- PASO 1: RETRIEVAL — buscamos contexto relevante en Chroma ---
    # El retriever genera el embedding del mensaje del usuario y busca
    # los top-3 fragmentos más similares semánticamente en la BD vectorial.
    retrieved_context = retrieve_context(query=user_message)

    if retrieved_context:
        logger.info("Contexto RAG recuperado, consultando LLM con contexto.")
    else:
        logger.info("No se encontró contexto RAG, el LLM responderá con conocimiento general.")

    # --- PASO 2: CONSTRUCCIÓN DEL PROMPT ---
    # Inyectamos el contexto recuperado en el system prompt.
    # Si no hay contexto, el campo queda como "No hay información disponible."
    system_content = SYSTEM_PROMPT_TEMPLATE.format(
        retrieved_context=retrieved_context or "No hay información disponible en las notas."
    )

    # --- PASO 3: GENERATION — el LLM genera la respuesta con el contexto ---
    llm = get_llm()
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=user_message),
    ]
    response = await llm.ainvoke(messages)
    reply = response.content.strip()

    logger.info(f"Respuesta LLM a {From}: {reply!r}")

    # --- PASO 4: RESPUESTA TwiML ---
    twiml = build_twiml_response(reply)
    return Response(content=twiml, media_type="application/xml")
