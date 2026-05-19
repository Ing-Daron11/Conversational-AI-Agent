"""
webhook.py — Endpoint de recepción de mensajes de WhatsApp (FASE 7 actualizado)

FLUJO COMPLETO (FASE 7):
  1. Twilio hace POST con el mensaje del usuario (form-data)
  2. Validación básica: mensaje no vacío, longitud máxima
  3. Rate limiting: verificar que el número no excedió el límite
  4. Cargar historial de conversación desde Redis (con fallback sin memoria)
  5. Ejecutar el agente (con circuit breaker + timeout)
  6. Loguear resultado estructurado (latencia, tools usadas)
  7. Actualizar Redis + persistir en PostgreSQL (background)
  8. Retornar TwiML al usuario

NUEVOS EN FASE 7:
  - Rate limiting por número de WhatsApp (Redis, Fixed Window)
  - Circuit breaker para el LLM (Ollama)
  - Fallbacks específicos por tipo de error
  - RequestLogger para latencia y tools_called
  - Validación de longitud de mensaje
"""

import logging
from fastapi import APIRouter, BackgroundTasks, Form, Request, Response

from app.agent.memory import ConversationMemory
from app.agent.orchestrator import run_agent
from app.models.database import save_conversation_to_db
from app.middleware.rate_limit import check_rate_limit
from app.core.fallbacks import (
    llm_circuit,
    FALLBACK_LLM_DOWN,
    FALLBACK_RATE_LIMITED,
    FALLBACK_MESSAGE_TOO_LONG,
)
from app.core.logger import RequestLogger, get_request_id

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_MESSAGE_LENGTH = 1500  # WhatsApp permite ~4096, limitamos a 1500 para el LLM


def build_twiml_response(message: str) -> str:
    """
    Construye una respuesta TwiML (Twilio Markup Language).
    Escapamos &, < y > para garantizar XML válido (output encoding — OWASP A03).
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


def twiml_reply(message: str) -> Response:
    """Helper: construye Response TwiML directamente."""
    return Response(content=build_twiml_response(message), media_type="application/xml")


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    Body: str = Form(default=""),
    From: str = Form(default=""),
    To: str = Form(default=""),
):
    """
    Endpoint principal del webhook con manejo completo de errores (FASE 7).
    """
    request_id = get_request_id()
    user_message = Body.strip()

    # ── Validación básica ──────────────────────────────────────────────────
    if not user_message:
        return twiml_reply("No recibí ningún mensaje. ¿En qué puedo ayudarte?")

    if len(user_message) > MAX_MESSAGE_LENGTH:
        logger.warning(
            "message_too_long",
            extra={"phone": From, "length": len(user_message), "request_id": request_id},
        )
        return twiml_reply(FALLBACK_MESSAGE_TOO_LONG)

    # ── Rate limiting ──────────────────────────────────────────────────────
    allowed, req_count = await check_rate_limit(From)
    if not allowed:
        return twiml_reply(FALLBACK_RATE_LIMITED)

    # ── Circuit breaker — verificar si el LLM está disponible ─────────────
    if not llm_circuit.is_available():
        logger.error(
            "llm_circuit_open",
            extra={"phone": From, "request_id": request_id},
        )
        return twiml_reply(FALLBACK_LLM_DOWN)

    # ── Pipeline principal con logging de latencia ─────────────────────────
    with RequestLogger(logger, phone=From, request_id=request_id) as req_log:
        try:
            # PASO 1: Memoria — historial desde Redis
            try:
                history = await ConversationMemory.get_history(From)
                chat_history = ConversationMemory.to_langchain_messages(history)
            except Exception as e:
                # Redis caído: continuamos sin historial (degradación elegante)
                logger.warning(f"redis_history_failed: {e}", extra={"phone": From})
                chat_history = []

            # PASO 2: Agente — LLM + tools
            reply = await run_agent(user_message, chat_history)
            llm_circuit.record_success()
            req_log.set_reply(reply)

            # PASO 3: Actualizar Redis (no bloquea si falla)
            try:
                await ConversationMemory.add_messages(From, user_message, reply)
                updated_history = await ConversationMemory.get_history(From)
                background_tasks.add_task(save_conversation_to_db, From, updated_history)
            except Exception as e:
                logger.warning(f"redis_update_failed: {e}", extra={"phone": From})
                # Guardar solo el par actual si Redis falló
                background_tasks.add_task(
                    save_conversation_to_db,
                    From,
                    [{"role": "user", "content": user_message},
                     {"role": "assistant", "content": reply}],
                )

        except Exception as e:
            llm_circuit.record_failure()
            logger.error(
                "agent_error",
                extra={"phone": From, "request_id": request_id, "error": str(e)},
                exc_info=True,
            )
            reply = FALLBACK_LLM_DOWN

    return twiml_reply(reply)

